import functools
from time import time
from typing import Any, Optional

import structlog
from prometheus_client import Histogram

logger = structlog.get_logger(__name__)

TIMED_DECORATOR_HISTOGRAM = Histogram(
    "posthog_timed_decorator_duration_seconds",
    "Duration of functions wrapped with @timed, by metric name.",
    labelnames=["name"],
)


def timed(name: str):
    def timed_decorator(func: Any) -> Any:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with TIMED_DECORATOR_HISTOGRAM.labels(name=name).time():
                return func(*args, **kwargs)

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
