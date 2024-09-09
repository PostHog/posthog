from enum import StrEnum
from prometheus_client import Counter
from sentry_sdk import set_tag
from collections.abc import Callable
from functools import wraps


class Feature(StrEnum):
    COHORT = "cohort"
    DASHBOARD = "dashboard"
    INSIGHT = "insight"
    QUERY = "query"


API_REQUESTS_COUNTER = Counter(
    "api_requests",
    "Number of API requests",
    labelnames=["endpoint", "method"],
)

API_REQUESTS_ERROR_COUNTER = Counter(
    "api_requests_error",
    "Number of errored API requests",
    labelnames=["endpoint", "method"],
)


def monitor(*, feature: Feature | None, endpoint: str, method: str) -> Callable:
    """
    Decorator to increment the API requests counter
    Sets sentry tags for the endpoint and method
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            API_REQUESTS_COUNTER.labels(endpoint=endpoint, method=method).inc()

            if feature:
                set_tag("feature", feature.value)
            try:
                return func(*args, **kwargs)
            except Exception:
                API_REQUESTS_ERROR_COUNTER.labels(endpoint=endpoint, method=method).inc()
                raise

        return wrapper

    return decorator
