from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils.timezone import now

import structlog
from prometheus_client import Counter, Gauge

from posthog.api.services.query import process_query_dict
from posthog.clickhouse.query_tagging import tag_queries
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Dashboard, Insight, InsightCachingState
from posthog.models.instance_setting import get_instance_setting
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.tasks.tasks import update_cache_task

logger = structlog.get_logger(__name__)

REQUEUE_DELAY = timedelta(hours=2)
MAX_ATTEMPTS = 3

INSIGHT_CACHE_WRITE_COUNTER = Counter("posthog_cloud_insight_cache_write", "A write to the redis insight cache")

CACHE_UPDATE_SKIPPED_COUNTER = Counter(
    "insight_cache_state_update_skipped", "Insight caching state is within target cache age and was not refreshed"
)
CACHE_UPDATE_SUCCEEDED_COUNTER = Counter(
    "insight_cache_state_update_succeeded", "Insight cache was successfully refreshed", labelnames=["is_dashboard"]
)
CACHE_UPDATE_FAILED_COUNTER = Counter(
    "insight_cache_state_update_failed", "Insight cache refresh failed", labelnames=["is_dashboard"]
)
CACHE_UPDATE_SHARED_GAUGE = Gauge(
    "insight_cache_state_update_rows_updated",
    "Number of rows updated during insight cache refresh. A single cache key can be shared by more than one insight/tile.",
)


def schedule_cache_updates():
    # :TODO: Separate celery queue for updates rather than limiting via this method
    PARALLEL_INSIGHT_CACHE = get_instance_setting("PARALLEL_DASHBOARD_ITEM_CACHE")

    to_update = fetch_states_in_need_of_updating(limit=PARALLEL_INSIGHT_CACHE)
    # :TRICKY: Schedule tasks and deduplicate by ID to avoid clashes
    representative_by_cache_key = set()
    for team_id, cache_key, caching_state_id in to_update:
        if (team_id, cache_key) not in representative_by_cache_key:
            representative_by_cache_key.add((team_id, cache_key))
            update_cache_task.delay(caching_state_id)

    InsightCachingState.objects.filter(pk__in=(id for _, _, id in to_update)).update(last_refresh_queued_at=now())

    if len(representative_by_cache_key) > 0:
        logger.warn(
            "Scheduled caches to be updated",
            candidates=len(to_update),
            tasks_created=len(representative_by_cache_key),
        )
    else:
        logger.warn("No caches were found to be updated")


def fetch_states_in_need_of_updating(limit: int) -> list[tuple[int, str, UUID]]:
    current_time = now()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT team_id, cache_key, id
            FROM posthog_insightcachingstate
            WHERE target_cache_age_seconds IS NOT NULL
            AND refresh_attempt < %(max_attempts)s
            AND (
                last_refresh IS NULL OR
                last_refresh < %(current_time)s - target_cache_age_seconds * interval '1' second
            )
            AND (
                last_refresh_queued_at IS NULL OR
                last_refresh_queued_at < %(last_refresh_queued_at_threshold)s
            )
            ORDER BY last_refresh ASC NULLS FIRST
            LIMIT %(limit)s
            """,
            {
                "max_attempts": MAX_ATTEMPTS,
                "current_time": current_time,
                "last_refresh_queued_at_threshold": current_time - REQUEUE_DELAY,
                "limit": limit,
            },
        )
        return cursor.fetchall()


def update_cache(caching_state_id: UUID):
    caching_state = InsightCachingState.objects.get(pk=caching_state_id)

    if caching_state.target_cache_age_seconds is None or (
        caching_state.last_refresh is not None
        and now() - caching_state.last_refresh < timedelta(seconds=caching_state.target_cache_age_seconds)
    ):
        CACHE_UPDATE_SKIPPED_COUNTER.inc()
        return

    insight, dashboard = _extract_insight_dashboard(caching_state)

    exception: Optional[Exception] = None
    cache_key: Optional[str] = None
    cache_type: Optional[str] = None
    result: Any = None

    metadata = {
        "team_id": insight.team_id,
        "insight_id": insight.pk,
        "dashboard_id": dashboard.pk if dashboard else None,
        "last_refresh": caching_state.last_refresh,
        "last_refresh_queued_at": caching_state.last_refresh_queued_at,
    }

    tag_queries(team_id=insight.team_id, insight_id=insight.pk, trigger="warming")
    if dashboard:
        tag_queries(dashboard_id=dashboard.pk)

    with upgrade_query(insight):
        try:
            response = process_query_dict(
                insight.team,
                insight.query,
                dashboard_filters_json=dashboard.filters if dashboard is not None else None,
                execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            )
            # TRICKY: `result` is null, because `process_query` already set the cache. `cache_type` also irrelevant
            cache_key, cache_type, result = getattr(response, "cache_key", None), None, None
        except Exception as err:
            capture_exception(err, metadata)
            exception = err

    if exception is None:
        assert cache_key is not None
        timestamp = now()
        rows_updated = update_cached_state(
            caching_state.team_id,
            cache_key,
            timestamp,
            {"result": result, "type": cache_type, "last_refresh": timestamp} if result is not None else None,
        )
        CACHE_UPDATE_SUCCEEDED_COUNTER.labels(is_dashboard=dashboard is not None).inc()
        CACHE_UPDATE_SHARED_GAUGE.inc(rows_updated)
        logger.warn(
            "Re-calculated insight cache",
            rows_updated=rows_updated,
            **metadata,
        )
    else:
        logger.warn(
            "Failed to re-calculate insight cache",
            exception=exception,
            **metadata,
            refresh_attempt=caching_state.refresh_attempt,
        )
        CACHE_UPDATE_FAILED_COUNTER.labels(is_dashboard=dashboard is not None).inc()

        if caching_state.refresh_attempt < MAX_ATTEMPTS:
            update_cache_task.apply_async(args=[caching_state_id], countdown=timedelta(minutes=10).total_seconds())

        InsightCachingState.objects.filter(pk=caching_state.pk).update(
            refresh_attempt=caching_state.refresh_attempt + 1,
            last_refresh_queued_at=now(),
        )


def update_cached_state(
    team_id: int,
    cache_key: str,
    timestamp: datetime | str,
    result: Any,
    ttl: Optional[int] = None,
):
    if result is not None:  # This is particularly the case for HogQL-based queries, which cache.set() on their own
        cache.set(cache_key, result, ttl if ttl is not None else settings.CACHED_RESULTS_TTL)
        INSIGHT_CACHE_WRITE_COUNTER.inc()

    # :TRICKY: We update _all_ states with same cache_key to avoid needless re-calculations and
    #   handle race conditions around cache_key changing.
    return InsightCachingState.objects.filter(team_id=team_id, cache_key=cache_key).update(
        last_refresh=timestamp, refresh_attempt=0
    )


def _extract_insight_dashboard(caching_state: InsightCachingState) -> tuple[Insight, Optional[Dashboard]]:
    if caching_state.dashboard_tile is not None:
        assert caching_state.dashboard_tile.insight is not None

        return (
            caching_state.dashboard_tile.insight,
            caching_state.dashboard_tile.dashboard,
        )
    else:
        return caching_state.insight, None
