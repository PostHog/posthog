import time

from django.conf import settings

import structlog
from celery import shared_task

from posthog.models.feature_flag.flags_cache import (
    cleanup_stale_expiry_tracking,
    get_cache_stats,
    refresh_expiring_flags_caches,
    update_flags_cache,
)
from posthog.models.feature_flag.local_evaluation import update_flag_caches
from posthog.models.team import Team
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def update_team_flags_cache(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.exception("Team does not exist", team_id=team_id)
        return

    update_flag_caches(team)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def update_team_service_flags_cache(team_id: int) -> None:
    """
    Update the service flags cache for a specific team.

    This task is triggered when feature flags change or when teams are created,
    ensuring the feature-flags service has fresh data in HyperCache.
    """
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.debug("Team does not exist for service flags cache update", team_id=team_id)
        HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(namespace="feature_flags", operation="update", result="failure").inc()
        return

    success = update_flags_cache(team)
    HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
        namespace="feature_flags", operation="update", result="success" if success else "failure"
    ).inc()


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sync_all_flags_cache() -> None:
    # Meant to ensure we have all flags cache in sync in case something failed

    # Only select the id from the team queryset
    for team_id in Team.objects.values_list("id", flat=True):
        update_team_flags_cache.delay(team_id)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_expiring_flags_cache_entries() -> None:
    """
    Periodic task to refresh flags caches before they expire.

    This task runs hourly and refreshes caches with TTL < 24 hours to prevent cache misses.

    Note: Most cache updates happen via Django signals when flags change.
    This job just prevents expiration-related cache misses.

    For initial cache build or schema migrations, use the management command:
        python manage.py warm_flags_cache [--invalidate-first]
    """

    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping flags cache refresh")
        return

    start_time = time.time()
    logger.info(
        "Starting flags cache sync",
        ttl_threshold_hours=settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,
        limit=settings.FLAGS_CACHE_REFRESH_LIMIT,
    )

    try:
        successful, failed = refresh_expiring_flags_caches(
            ttl_threshold_hours=settings.FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,
            limit=settings.FLAGS_CACHE_REFRESH_LIMIT,
        )

        # Note: Teams processed metrics are pushed to Pushgateway by
        # cache_expiry_manager.refresh_expiring_caches() via push_hypercache_teams_processed_metrics()

        # Scan after refresh for metrics (pushes to Pushgateway via get_cache_stats)
        stats_after = get_cache_stats()

        duration = time.time() - start_time

        logger.info(
            "Completed flags cache refresh",
            successful_refreshes=successful,
            failed_refreshes=failed,
            total_cached=stats_after.get("total_cached", 0),
            total_teams=stats_after.get("total_teams", 0),
            cache_coverage=stats_after.get("cache_coverage", "unknown"),
            ttl_distribution=stats_after.get("ttl_distribution", {}),
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.exception(
            "Failed to complete flags cache batch refresh",
            error=str(e),
            duration_seconds=duration,
        )
        raise


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def cleanup_stale_flags_expiry_tracking_task() -> None:
    """
    Periodic task to clean up stale entries in the flags cache expiry tracking sorted set.

    Removes entries for teams that no longer exist in the database.
    Runs daily to prevent sorted set bloat from deleted teams.
    """
    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping flags expiry tracking cleanup")
        return

    try:
        removed_count = cleanup_stale_expiry_tracking()
        logger.info("Completed flags expiry tracking cleanup", removed_count=removed_count)
    except Exception as e:
        logger.exception("Failed to cleanup flags expiry tracking", error=str(e))
        raise
