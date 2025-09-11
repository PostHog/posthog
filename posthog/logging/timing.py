import functools
from time import time
from typing import Any, Optional

import structlog
from statshog.defaults.django import statsd

logger = structlog.get_logger(__name__)


def timed(name: str):
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


def timed_log(name: Optional[str] = None):
    def timed_decorator(func: Any) -> Any:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            fn_name = name or func.__name__
            start = time()
            try:
                return func(*args, **kwargs)
            finally:
                duration = round((time() - start) * 1000, 1)
                print(  # noqa T201
                    f"Timed function: {fn_name} took {duration}ms with args",
                    {"args": args, "kwargs": kwargs},
                )

        return wrapper

    return timed_decorator
