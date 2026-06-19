"""
Celery tasks for team metadata cache management.

Provides async tasks for updating and syncing team metadata caches.
"""

import time
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

import structlog
from celery import shared_task

from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.storage.team_metadata_cache import (
    cleanup_stale_expiry_tracking,
    clear_team_metadata_cache,
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
    if organization_id is not None:
        team_ids = Team.objects.filter(organization_id=organization_id).values_list("id", flat=True)
    elif project_id is not None:
        team_ids = Team.objects.filter(project_id=project_id).values_list("id", flat=True)
    else:
        return

    for team_id in team_ids:
        update_team_metadata_cache_task.delay(team_id)


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
        successful, failed = refresh_expiring_caches(ttl_threshold_hours=24)

        # Note: Teams processed metrics are pushed to Pushgateway by
        # cache_expiry_manager.refresh_expiring_caches() via push_hypercache_teams_processed_metrics()

        # Scan after refresh for metrics (pushes to Pushgateway via get_cache_stats)
        stats_after = get_cache_stats()

        duration = time.time() - start_time

        logger.info(
            "Completed team metadata cache refresh",
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
            "Failed to complete team metadata batch refresh",
            error=str(e),
            duration_seconds=duration,
        )
        raise


@receiver(post_save, sender=Team)
def update_team_metadata_cache_on_save(sender: type[Team], instance: Team, created: bool, **kwargs: Any) -> None:
    """Update team metadata cache when a Team is saved."""
    if not settings.FLAGS_REDIS_URL:
        return

    def enqueue_task() -> None:
        try:
            update_team_metadata_cache_task.delay(instance.id)
        except Exception as e:
            _record_enqueue_failure()
            logger.exception(
                "Failed to enqueue cache update task",
                team_id=instance.id,
                error=str(e),
            )

    # Use transaction.on_commit to ensure the database changes are committed
    # before we update the cache
    transaction.on_commit(enqueue_task)


@receiver(pre_delete, sender=Team)
def clear_team_metadata_cache_on_delete(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    """Clear team metadata cache when a Team is deleted."""
    if not settings.FLAGS_REDIS_URL:
        return

    # NB: For unit tests, only clear Redis to avoid S3 timestamp issues with frozen time
    kinds = ["redis"] if settings.TEST else None
    clear_team_metadata_cache(instance, kinds=kinds)


def _record_enqueue_failure() -> None:
    HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
        namespace="team_metadata", cache_name="team_metadata", operation="enqueue", result="failure"
    ).inc()


def _name_may_have_changed(update_fields: frozenset[str] | None) -> bool:
    """Whether a save could have touched the `name` field.

    A `None` update_fields means a full save, where we can't tell, so we assume it might have.
    """
    return update_fields is None or "name" in update_fields


def _enqueue_related_team_metadata_fanout(*, organization_id: int | None = None, project_id: int | None = None) -> None:
    try:
        update_related_teams_metadata_cache_task.delay(organization_id=organization_id, project_id=project_id)
    except Exception as e:
        _record_enqueue_failure()
        logger.exception(
            "Failed to enqueue related team metadata fan-out",
            organization_id=organization_id,
            project_id=project_id,
            error=str(e),
        )


# Organization and project names are denormalized into team metadata, but only the Team signal
# refreshes the cache. These receivers cover org/project renames, which never touch the Team row.
# Deletes need no receiver: both FKs cascade to Team, firing the Team pre_delete handler above.
@receiver(post_save, sender=Organization)
def update_team_metadata_cache_on_organization_save(
    sender: type[Organization], instance: Organization, created: bool, **kwargs: Any
) -> None:
    """Refresh dependent team metadata caches when an organization is renamed."""
    if created or not settings.FLAGS_REDIS_URL:
        return
    if not _name_may_have_changed(kwargs.get("update_fields")):
        return

    transaction.on_commit(lambda: _enqueue_related_team_metadata_fanout(organization_id=instance.id))


@receiver(post_save, sender=Project)
def update_team_metadata_cache_on_project_save(
    sender: type[Project], instance: Project, created: bool, **kwargs: Any
) -> None:
    """Refresh dependent team metadata caches when a project is renamed."""
    if created or not settings.FLAGS_REDIS_URL:
        return
    if not _name_may_have_changed(kwargs.get("update_fields")):
        return

    transaction.on_commit(lambda: _enqueue_related_team_metadata_fanout(project_id=instance.id))


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
