from enum import StrEnum
from prometheus_client import Counter
from sentry_sdk import set_tag
from collections.abc import Callable


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


def monitor(*, feature: Feature | None, endpoint: str, method: str) -> Callable:
    """
    Decorator to increment the API requests counter
    Sets sentry tags for the endpoint and method
    """

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            API_REQUESTS_COUNTER.labels(endpoint=endpoint, method=method).inc()

            if feature:
                set_tag("feature", feature.value)

            return func(*args, **kwargs)

        return wrapper

    return decorator
