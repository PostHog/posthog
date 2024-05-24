from datetime import datetime, timedelta
from time import perf_counter
from typing import Any, Optional
from uuid import UUID

import structlog
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils.timezone import now
from prometheus_client import Counter
from sentry_sdk.api import capture_exception
from statshog.defaults.django import statsd

from posthog.api.services.query import process_query_dict
from posthog.caching.calculate_results import calculate_for_filter_based_insight
from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql_queries.legacy_compatibility.flagged_conversion_manager import flagged_conversion_to_query_based
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Dashboard, Insight, InsightCachingState
from posthog.models.instance_setting import get_instance_setting
from posthog.tasks.tasks import update_cache_task

logger = structlog.get_logger(__name__)

REQUEUE_DELAY = timedelta(hours=2)
MAX_ATTEMPTS = 3

insight_cache_write_counter = Counter("posthog_cloud_insight_cache_write", "A write to the redis insight cache")


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
        statsd.incr("caching_state_update_skipped")
        return

    insight, dashboard = _extract_insight_dashboard(caching_state)
    start_time = perf_counter()

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

    tag_queries(team_id=insight.team_id, insight_id=insight.pk)
    if dashboard:
        tag_queries(dashboard_id=dashboard.pk)

    with flagged_conversion_to_query_based(insight):
        try:
            if insight.query:
                response = process_query_dict(
                    insight.team,
                    insight.query,
                    dashboard_filters_json=dashboard.filters if dashboard is not None else None,
                    execution_mode=ExecutionMode.CALCULATION_ALWAYS,
                )
                # TRICKY: `result` is null, because `process_query` already set the cache. `cache_type` also irrelevant
                cache_key, cache_type, result = getattr(response, "cache_key", None), None, None
            else:
                cache_key, cache_type, result = calculate_for_filter_based_insight(insight=insight, dashboard=dashboard)
        except Exception as err:
            capture_exception(err, metadata)
            exception = err

    duration = perf_counter() - start_time
    if exception is None:
        assert cache_key is not None
        timestamp = now()
        rows_updated = update_cached_state(
            caching_state.team_id,
            cache_key,
            timestamp,
            {"result": result, "type": cache_type, "last_refresh": timestamp} if result is not None else None,
        )
        statsd.incr("caching_state_update_success")
        statsd.incr("caching_state_update_rows_updated", rows_updated)
        statsd.timing("caching_state_update_success_timing", duration)
        logger.warn(
            "Re-calculated insight cache",
            rows_updated=rows_updated,
            duration=duration,
            **metadata,
        )
    else:
        logger.warn(
            "Failed to re-calculate insight cache",
            exception=exception,
            duration=duration,
            **metadata,
            refresh_attempt=caching_state.refresh_attempt,
        )
        statsd.incr("caching_state_update_errors")

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
    insight_cache_write_counter.inc()

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
