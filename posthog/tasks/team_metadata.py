"""
Celery tasks for team metadata cache management.

Provides async tasks for updating and syncing team metadata caches.
"""

import time

from django.conf import settings

import structlog
from celery import shared_task

from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.storage.team_metadata_cache import (
    cleanup_stale_expiry_tracking,
    get_cache_stats,
    refresh_expiring_caches,
    update_team_metadata_cache,
)
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def update_team_metadata_cache_task(team_id: int) -> None:
    """
    Update the metadata cache for a specific team.

    This task is triggered by Django signals when a team is saved/updated.

    Args:
        team_id: The ID of the team to update
    """
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.debug("Team does not exist for metadata cache update", team_id=team_id)
        HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
            namespace="team_metadata", cache_name="team_metadata", operation="update", result="failure"
        ).inc()
        return

    success = update_team_metadata_cache(team)
    HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
        namespace="team_metadata",
        cache_name="team_metadata",
        operation="update",
        result="success" if success else "failure",
    ).inc()


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def update_related_teams_metadata_cache_task(organization_id: int | None = None, project_id: int | None = None) -> None:
    """
    Refresh team metadata caches for every team under a changed organization or project.

    Organization and project names are denormalized into each team's cached metadata, so renaming
    either must refresh every dependent team. Fanning out here keeps the originating request O(1):
    the signal enqueues a single task no matter how many teams the org or project owns, and each
    per-team update runs as its own task so the work spreads across workers.
    """
    try:
        if organization_id is not None:
            team_ids = Team.objects.filter(organization_id=organization_id).values_list("id", flat=True)
        elif project_id is not None:
            team_ids = Team.objects.filter(project_id=project_id).values_list("id", flat=True)
        else:
            return

        for team_id in team_ids:
            update_team_metadata_cache_task.delay(team_id)
    except Exception as e:
        logger.exception(
            "Failed to fan out related team metadata cache refresh",
            organization_id=organization_id,
            project_id=project_id,
            error=str(e),
        )
        raise


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_expiring_team_metadata_cache_entries() -> None:
    """
    Periodic task to refresh team metadata caches before they expire.

    This task runs hourly and refreshes caches with TTL < 24 hours to prevent cache misses.

    Note: Most cache updates happen via Django signals when teams change.
    This job just prevents expiration-related cache misses.

    For initial cache build or schema migrations, use the management command:
        python manage.py warm_team_metadata_cache
    """

    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping team metadata cache refresh")
        return

    start_time = time.time()
    logger.info("Starting team metadata cache sync")

    try:
        counts = refresh_expiring_caches(ttl_threshold_hours=24)

        # Note: Teams processed metrics are pushed to Pushgateway by
        # cache_expiry_manager.refresh_expiring_caches() via push_hypercache_teams_processed_metrics()

        # Scan after refresh for metrics (pushes to Pushgateway via get_cache_stats)
        stats_after = get_cache_stats()

        duration = time.time() - start_time

        logger.info(
            "Completed team metadata cache refresh",
            successful_refreshes=counts.successful,
            failed_refreshes=counts.failed,
            total_cached=stats_after.get("total_cached", 0),
            total_teams=stats_after.get("total_teams", 0),
            cache_coverage=stats_after.get("cache_coverage", "unknown"),
            ttl_distribution=stats_after.get("ttl_distribution", {}),
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.exception(
            "Failed to complete team metadata batch refresh",
            error=str(e),
            duration_seconds=duration,
        )
        raise


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def cleanup_stale_expiry_tracking_task() -> None:
    """
    Periodic task to clean up stale entries in the expiry tracking sorted set.

    Removes entries for teams that no longer exist in the database.
    Runs daily to prevent sorted set bloat from deleted teams.
    """
    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping expiry tracking cleanup")
        return

    try:
        removed_count = cleanup_stale_expiry_tracking()
        logger.info("Completed expiry tracking cleanup", removed_count=removed_count)
    except Exception as e:
        logger.exception("Failed to cleanup expiry tracking", error=str(e))
        raise
