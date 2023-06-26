import functools
from typing import Any
from typing import Any, Optional
from prometheus_client import Histogram

from statshog.defaults.django import statsd


def statsd_timed(name: str):
    def timed_decorator(func: Any) -> Any:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            timer = statsd.timer(name).start()
            try:
                return func(*args, **kwargs)
            finally:
                timer.stop()

        return wrapper

    return timed_decorator


def timed(name: Optional[str] = None):
    def timed_decorator(func: Any) -> Any:
        histogram = Histogram(f"timed_function_{name or func.__name__}")

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with histogram.time():
                return func(*args, **kwargs)

        return wrapper

    return timed_decorator
