from contextlib import contextmanager
from functools import wraps

from django.dispatch import Signal
from django.dispatch.dispatcher import receiver

is_muted = False

# Used for any model that requires an activity log of changes
# To use this, a model must either:
# 1. Include ModelActivityMixin in the model's inheritance
# 2. Or override the save method and call this signal manually
# See FeatureFlag for an example.
model_activity_signal = Signal()


def mutable_receiver(*args, **kwargs):
    """
    Decorator for a django signal handler which can be turned off during mass deletes.
    """

    def _inner(handler):
        @receiver(*args, **kwargs)
        @wraps(handler)
        def new_handler(*f_args, **f_kwargs):
            if not is_muted:
                handler(*f_args, **f_kwargs)

        return new_handler

    return _inner


@contextmanager
def mute_selected_signals():
    """
    Code in this block does not call _any_ of the receive hooks set up with @mutable_receiver.

    This can be useful for mass object deletion scenarios, where a given hook might be called thousands of times.
    """

    global is_muted
    try:
        is_muted = True
        yield
    finally:
        is_muted = False
