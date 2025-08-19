from datetime import datetime
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from prometheus_client import Counter, Histogram

from posthog.cache_utils import OrjsonJsonSerializer
from posthog.utils import get_safe_cache
from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.metrics import LABEL_TEAM_ID
from posthog.clickhouse.query_tagging import get_query_tag_value

# Prometheus metrics for query cache monitoring
QUERY_CACHE_WRITE_COUNTER = Counter(
    "posthog_query_cache_write_total",
    "When a query result was persisted in the cache.",
    labelnames=[LABEL_TEAM_ID],
)

QUERY_CACHE_HIT_COUNTER = Counter(
    "posthog_query_cache_hit_total",
    "Whether we could fetch the query from the cache or not.",
    labelnames=[LABEL_TEAM_ID, "cache_hit", "trigger"],
)

CACHE_READ_BYTES_COUNTER = Counter(
    "posthog_query_cache_read_bytes_total",
    "Total bytes read from cache (uncompressed JSON)",
    labelnames=[LABEL_TEAM_ID],
)

CACHE_WRITE_BYTES_COUNTER = Counter(
    "posthog_query_cache_write_bytes_total",
    "Total bytes written to cache (uncompressed JSON)",
    labelnames=[LABEL_TEAM_ID],
)

CACHE_DATA_SIZE_HISTOGRAM = Histogram(
    "posthog_query_cache_data_size_bytes",
    "Distribution of cache data sizes in bytes (uncompressed JSON)",
    labelnames=[LABEL_TEAM_ID, "operation"],
    buckets=[
        100,  # Small responses < 100B
        1000,  # 100B - 1KB
        10000,  # 1KB - 10KB
        100000,  # 10KB - 100KB
        1000000,  # 100KB - 1MB
        10000000,  # 1MB - 10MB
        100000000,  # 10MB - 100MB
        float("inf"),
    ],
)


def is_cache_warming() -> bool:
    """Check if current request is cache warming and should be excluded from metrics."""
    return (get_query_tag_value("trigger") or "").startswith("warming")


def count_query_cache_hit(team_id: int, hit: str, trigger: str = "") -> None:
    """Count cache hit/miss, excluding cache warming requests."""
    if is_cache_warming():
        return
    QUERY_CACHE_HIT_COUNTER.labels(team_id=team_id, cache_hit=hit, trigger=trigger).inc()


def count_query_cache_write(team_id: int) -> None:
    """Count cache write operations."""
    QUERY_CACHE_WRITE_COUNTER.labels(team_id=team_id).inc()


def count_cache_data_size(team_id: int, data_size: int, operation: str) -> None:
    """Count cache data size metrics, excluding cache warming for reads."""
    if operation == "read" and is_cache_warming():
        return

    if operation == "read":
        CACHE_READ_BYTES_COUNTER.labels(team_id=team_id).inc(data_size)
    else:
        CACHE_WRITE_BYTES_COUNTER.labels(team_id=team_id).inc(data_size)
    CACHE_DATA_SIZE_HISTOGRAM.labels(team_id=team_id, operation=operation).observe(data_size)


class DjangoCacheQueryCacheManager(QueryCacheManagerBase):
    """
    Storing query results in Django cache (typically Redis) keyed by the hash of the query (cache_key param).
    '{cache_key}' -> query_results

    Uses Redis sorted sets (from base class) to store the time query results were calculated.
    'cache_timestamps:{team_id}' -> '{self.insight_id}:{self.dashboard_id or ''}' -> timestamp (epoch time when calculated)
    """

    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        fresh_response_serialized = OrjsonJsonSerializer({}).dumps(response)
        data_size = len(fresh_response_serialized)

        # Track cache write metrics
        count_query_cache_write(self.team_id)
        count_cache_data_size(self.team_id, data_size, "write")

        cache.set(self.cache_key, fresh_response_serialized, settings.CACHED_RESULTS_TTL)

        if target_age:
            self.update_target_age(target_age)
        else:
            self.remove_last_refresh()

    def get_cache_data(self) -> Optional[dict]:
        cached_response_bytes: Optional[bytes] = get_safe_cache(self.cache_key)

        if not cached_response_bytes:
            return None

        # Track successful read data size metrics (respects cache warming exclusion)
        data_size = len(cached_response_bytes)
        count_cache_data_size(self.team_id, data_size, "read")

        return OrjsonJsonSerializer({}).loads(cached_response_bytes)
