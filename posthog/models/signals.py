from contextlib import contextmanager
from functools import wraps

from django.dispatch.dispatcher import receiver

is_muted = False


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
def mute_signals():
    global is_muted
    try:
        is_muted = True
    finally:
        is_muted = False
