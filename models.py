from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
from denseNet import *

from tensorflow.contrib.slim.nets import resnet_v1


slim = tf.contrib.slim

def lstm_cell(hidden_units=256):
    return tf.nn.rnn_cell.LSTMCell(hidden_units,
                                use_peepholes=True,
                                cell_clip=100,
                                state_is_tuple=True)

def recurrent_model(net, hidden_units=256, number_of_outputs=2):
    """Adds the recurrent network on top of the spatial
       audio / video / audio-visual model.

    Args:
       net: A `Tensor` of dimensions [batch_size, seq_length, num_features].
       hidden_units: The number of hidden units of the LSTM cell.
       num_classes: The number of classes.
    Returns:
       The prediction of the network.
    """

    batch_size, seq_length, num_features = net.get_shape().as_list()

    stacked_lstm = tf.nn.rnn_cell.MultiRNNCell([lstm_cell() for _ in range(2)], state_is_tuple=True)

    # We have to specify the dimensionality of the Tensor so we can allocate
    # weights for the fully connected layers.
    outputs, _ = tf.nn.dynamic_rnn(stacked_lstm, net, dtype=tf.float32)
    net = tf.reshape(outputs, (batch_size * seq_length, hidden_units))

    prediction = slim.layers.linear(net, number_of_outputs)

    return tf.reshape(prediction, (batch_size, seq_length, number_of_outputs))

def video_model(video_frames=None, audio_frames=None, is_training=True, is_resnet=False):
    """Creates the video model.

    Args:
        video_frames: A tensor that contains the video input.
        audio_frames: not needed (leave None).
        is_training : if the model is in training mode
        is_resnet   : whether to use the resnet or the densenet
    Returns:
        The video model.
    """

    with tf.variable_scope("video_model"):
        batch_size, seq_length, height, width, channels = video_frames.get_shape().as_list()

        video_input = tf.reshape(video_frames, (batch_size * seq_length, height, width, channels))
        video_input = tf.cast(video_input, tf.float32)

        if is_resnet:
            features, end_points = resnet_v1.resnet_v1_50(video_input, None, is_training)
            features = tf.reshape(features, (batch_size, seq_length, int(features.get_shape()[3])))
        else:
            features = denseNet(video_input, None, is_training)
            features = tf.reshape(features, (batch_size, seq_length, -1))
    return features

def audio_model(video_frames=None, audio_frames=None, is_training=None, conv_filters=40, is_densenet=True):
    """Creates the audio model.

    Args:
        video_frames: not needed (leave None).
        audio_frames: A tensor that contains the audio input.
        is_training : if the model is in training mode
        conv_filters: The number of convolutional filters to use.
        is_densenet : Whether the densenet should be used or not
    Returns:
        The audio model.
    """

    with tf.variable_scope("audio_model"):
      batch_size, seq_length, num_features = audio_frames.get_shape().as_list()
      audio_input = tf.reshape(audio_frames, [batch_size * seq_length, 1, num_features, 1])

      if is_densenet:
          # Arguments:
          # (inputs,num_classes,is_training,total_blocks,depth
          # growth_rate,dropout_rate,b_mode,reduction,pool,final_pool,is_audio)
          net = denseNet(audio_input, None, is_training,
                         1, 5, 12, 0.2, False, 1, (1, 2), (1, 2), True)
          net = tf.reshape(net, (batch_size, seq_length, -1))
      else:
          with slim.arg_scope([slim.layers.conv2d], padding='SAME'):
            net = slim.dropout(audio_input)
            net = slim.layers.conv2d(net, conv_filters, (1, 20))

            # Subsampling of the signal to 8KhZ.
            net = tf.nn.max_pool(
                net,
                ksize=[1, 1, 2, 1],
                strides=[1, 1, 2, 1],
                padding='SAME',
                name='pool1')

            # Original model had 400 output filters for the second conv layer
            # but this trains much faster and achieves comparable accuracy.
            net = slim.layers.conv2d(net, conv_filters, (1, 40))

            net = tf.reshape(net, (batch_size * seq_length, num_features // 2, conv_filters, 1))

            # Pooling over the feature maps.
            net = tf.nn.max_pool(
                net,
                ksize=[1, 1, 10, 1],
                strides=[1, 1, 10, 1],
                padding='SAME',
                name='pool2')

          net = tf.reshape(net, (batch_size, seq_length, num_features // 2 * 4 ))

    return net


def combined_model(video_frames, audio_frames, is_training):
    """Creates the audio-visual model.

    Args:
        video_frames: A tensor that contains the video input.
        audio_frames: A tensor that contains the audio input.
    Returns:
        The audio-visual model.
    """

    audio_features = audio_model([], audio_frames)
    visual_features = video_model(video_frames,[], is_training)

    return tf.concat((audio_features, visual_features), 2, name='concat')


def get_model(name):
    """Returns the recurrent model.

    Args:
        name: one of the 'audio', 'video', or 'both'
    Returns:
        The recurrent model.
    """

    name_to_fun = {'audio': audio_model, 'video': video_model, 'both': combined_model}

    if name in name_to_fun:
        model = name_to_fun[name]
    else:
        raise ValueError('Requested name [{}] not a valid model'.format(name))

    def wrapper(*args, **kwargs):
        return recurrent_model(model(*args), **kwargs)

    return wrapper
