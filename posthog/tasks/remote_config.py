import time

from django.conf import settings

import structlog
from celery import shared_task

from posthog.models.remote_config import RemoteConfig
from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage.remote_config_cache import cleanup_stale_expiry_tracking, get_cache_stats, refresh_expiring_caches
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    soft_time_limit=300,
    time_limit=360,
)
@skip_team_scope_audit
def update_team_remote_config(team_id: int, bypass_recordings_quota_cache: bool = False) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.exception("Team does not exist", team_id=team_id)
        return

    try:
        remote_config = RemoteConfig.objects.get(team=team)
    except RemoteConfig.DoesNotExist:
        remote_config = RemoteConfig(team=team)

    remote_config.sync(bypass_recordings_quota_cache=bypass_recordings_quota_cache)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def sync_all_remote_configs() -> None:
    # Meant to ensure we have all configs in sync in case something failed

    # Only select the id from the team queryset
    for team_id in Team.objects.values_list("id", flat=True):
        update_team_remote_config.delay(team_id)


@shared_task(
    ignore_result=True,
    # Long batch loop kept off the latency-sensitive default queue.
    queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value,
    # Bound the worker slot so a stalled iteration can't pin it.
    soft_time_limit=15 * 60,
    time_limit=16 * 60,
)
def refresh_expiring_remote_config_cache_entries() -> None:
    """
    Hourly task that re-stamps array/config.json cache entries expiring within 24h,
    keeping the dedicated flags Redis warm so reads don't fall through to S3.
    """
    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping remote config cache refresh")
        return

    start_time = time.time()
    logger.info("Starting remote config cache refresh")

    try:
        successful, failed = refresh_expiring_caches(ttl_threshold_hours=24)

        # Scan after refresh to push coverage/TTL metrics to Pushgateway.
        stats_after = get_cache_stats()

        duration = time.time() - start_time

        logger.info(
            "Completed remote config cache refresh",
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
            "Failed to complete remote config cache refresh",
            error=str(e),
            duration_seconds=duration,
        )
        raise


@shared_task(
    ignore_result=True,
    # Shares the refresh task's queue.
    queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value,
    soft_time_limit=5 * 60,
    time_limit=6 * 60,
)
def cleanup_stale_remote_config_expiry_tracking_task() -> None:
    """
    Daily task that prunes expiry-tracking entries for deleted teams, keeping the
    remote_config_cache_expiry sorted set from growing unbounded.
    """
    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping remote config expiry tracking cleanup")
        return

    try:
        removed_count = cleanup_stale_expiry_tracking()
        logger.info("Completed remote config expiry tracking cleanup", removed_count=removed_count)
    except Exception as e:
        logger.exception("Failed to cleanup remote config expiry tracking", error=str(e))
        raise
