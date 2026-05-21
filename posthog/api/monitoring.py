from collections.abc import Callable
from enum import StrEnum
from functools import wraps

from prometheus_client import Counter

from posthog.clickhouse.query_tagging import tag_queries


# Keep values in sync with `posthog.clickhouse.query_tagging.Feature` — pydantic validates
# the `feature` field on `QueryTags` against that enum, so a value here that is missing
# there will fail at runtime.
class Feature(StrEnum):
    COHORT = "cohort"
    DASHBOARD = "dashboard"
    DEBUG_QUERY = "debug_query"
    INSIGHT = "insight"
    LLM_ANALYTICS = "llm_analytics"
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
    Tags endpoints and methods with the feature name
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            API_REQUESTS_COUNTER.labels(endpoint=endpoint, method=method).inc()

            if feature:
                tag_queries(feature=feature.value)
            try:
                return func(*args, **kwargs)
            except Exception:
                API_REQUESTS_ERROR_COUNTER.labels(endpoint=endpoint, method=method).inc()
                raise

        return wrapper

    return decorator
