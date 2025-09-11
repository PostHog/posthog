from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from typing import NamedTuple, Optional

from django.conf import settings
from django.core.cache import cache

from prometheus_client import CollectorRegistry, Counter, Histogram

from posthog.cache_utils import OrjsonJsonSerializer
from posthog.clickhouse.query_tagging import get_query_tag_value
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.metrics import LABEL_TEAM_ID, pushed_metrics_registry
from posthog.utils import get_safe_cache


class CacheMetrics(NamedTuple):
    hit_counter: Counter
    write_counter: Counter
    bytes_counter: Counter
    size_histogram: Histogram


# Default metrics for long-running processes (lazy-initialized)
_default_metrics: Optional[CacheMetrics] = None


def _is_celery_context() -> bool:
    """Check if we're running in a Celery task context."""
    try:
        from celery import current_task

        return bool(current_task)
    except Exception as e:
        capture_exception(
            e,
            {
                "context": "celery_context_detection",
                "tag": "analytics-platform",
            },
        )
        return False


def _is_temporal_context() -> bool:
    """Check if we're running in a Temporal activity context."""
    try:
        import temporalio.activity

        temporalio.activity.info()
        return True
    except RuntimeError:
        # Expected when not in a Temporal activity - don't log
        return False
    except Exception as e:
        capture_exception(
            e,
            {
                "context": "temporal_context_detection",
                "tag": "analytics-platform",
            },
        )
        return False


def _is_short_lived_context() -> bool:
    return _is_celery_context() or _is_temporal_context()


def _create_cache_metrics(registry: Optional[CollectorRegistry] = None) -> CacheMetrics:
    """Create all cache metrics with optional registry."""
    hit_counter = Counter(
        name="posthog_query_cache_hit_total",
        documentation="Whether we could fetch the query from the cache or not.",
        labelnames=[LABEL_TEAM_ID, "cache_hit", "trigger"],
        registry=registry,
    )

    write_counter = Counter(
        name="posthog_query_cache_write_total",
        documentation="When a query result was persisted in the cache.",
        labelnames=[LABEL_TEAM_ID],
        registry=registry,
    )

    bytes_counter = Counter(
        name="posthog_query_cache_write_bytes_total",
        documentation="Total bytes written to cache (uncompressed JSON)",
        labelnames=[LABEL_TEAM_ID],
        registry=registry,
    )

    size_histogram = Histogram(
        name="posthog_query_cache_write_size_bytes",
        documentation="Distribution of cache write data sizes in bytes (uncompressed JSON)",
        labelnames=[LABEL_TEAM_ID],
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
        registry=registry,
    )

    return CacheMetrics(hit_counter, write_counter, bytes_counter, size_histogram)


def _get_cache_metrics(registry: Optional[CollectorRegistry] = None) -> CacheMetrics:
    if registry is not None:
        return _create_cache_metrics(registry)
    else:
        global _default_metrics
        if _default_metrics is None:
            _default_metrics = _create_cache_metrics()
        return _default_metrics


@contextmanager
def get_cache_metrics_context(registry_name: str) -> Generator[CacheMetrics, None, None]:
    """Context manager that yields the appropriate cache metrics based on execution context."""
    if _is_short_lived_context():
        with pushed_metrics_registry(registry_name) as registry:
            yield _get_cache_metrics(registry)
    else:
        yield _get_cache_metrics()


def is_cache_warming() -> bool:
    return (get_query_tag_value("trigger") or "").startswith("warming")


def count_query_cache_hit(team_id: int, hit: str, trigger: str = "") -> None:
    """Count cache hit/miss, excluding cache warming requests."""
    if is_cache_warming():
        return

    with get_cache_metrics_context("query_cache_hits") as metrics:
        metrics.hit_counter.labels(team_id=team_id, cache_hit=hit, trigger=trigger).inc()


def count_cache_write_data(team_id: int, data_size: int) -> None:
    """Count cache write operations and data size metrics."""
    with get_cache_metrics_context("query_cache_writes") as metrics:
        metrics.write_counter.labels(team_id=team_id).inc()
        metrics.bytes_counter.labels(team_id=team_id).inc(data_size)
        metrics.size_histogram.labels(team_id=team_id).observe(data_size)


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

        cache.set(self.cache_key, fresh_response_serialized, settings.CACHED_RESULTS_TTL)

        if target_age:
            self.update_target_age(target_age)
        else:
            self.remove_last_refresh()

        # Track cache write metrics
        count_cache_write_data(self.team_id, data_size)

    def get_cache_data(self) -> Optional[dict]:
        cached_response_bytes: Optional[bytes] = get_safe_cache(self.cache_key)

        if not cached_response_bytes:
            return None

        return OrjsonJsonSerializer({}).loads(cached_response_bytes)
