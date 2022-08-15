from typing import Any

from statshog.defaults.django import statsd


def timed(name: str):
    def timed_decorator(func: Any) -> Any:
        def wrapper(*args, **kwargs):
            timer = statsd.timer(name).start()
            try:
                return func(*args, **kwargs)
            finally:
                timer.stop()

        return wrapper

    return timed_decorator
