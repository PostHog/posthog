import time

from django.conf import settings

import structlog
from celery import shared_task

from posthog.models.remote_config import RemoteConfig, refresh_expiring_remote_config_caches
from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
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


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def refresh_expiring_remote_config_cache_entries() -> None:
    """
    Periodic task to refresh `array/config.json` HyperCache entries before
    they fall off the 30-day TTL. Without this, teams whose config hasn't
    changed in 30 days see their dedicated-Redis key expire and reads fall
    through to S3 until something else rewrites the cache.

    Mirrors `refresh_expiring_team_metadata_cache_entries`. See
    `posthog/models/remote_config.py::REMOTE_CONFIG_CACHE_EXPIRY_SORTED_SET`
    for the sorted-set the refresh queries.

    Fixes https://github.com/PostHog/posthog/issues/65026.
    """
    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping remote config cache refresh")
        return

    start_time = time.time()
    logger.info("Starting remote config cache sync")

    try:
        successful, failed = refresh_expiring_remote_config_caches(ttl_threshold_hours=24)
        duration = time.time() - start_time
        logger.info(
            "Completed remote config cache refresh",
            successful_refreshes=successful,
            failed_refreshes=failed,
            duration_seconds=duration,
        )
    except Exception as e:
        duration = time.time() - start_time
        logger.exception(
            "Failed remote config cache refresh",
            error=str(e),
            duration_seconds=duration,
        )
