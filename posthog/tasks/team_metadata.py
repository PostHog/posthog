"""
Celery tasks for team metadata cache management.

Provides async tasks for updating and syncing team metadata caches.
"""

from typing import Any

from django.db import transaction
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

import structlog
from celery import shared_task

from posthog.models.team import Team
from posthog.storage.team_metadata_cache import clear_team_metadata_cache, update_team_metadata_cache
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
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
        logger.warning("Team does not exist for metadata cache update", team_id=team_id)
        return

    success = update_team_metadata_cache(team)
    if success:
        logger.info(
            "Successfully updated team metadata cache",
            team_id=team_id,
        )
    else:
        logger.error(
            "Failed to update team metadata cache",
            team_id=team_id,
        )


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_stale_team_metadata_cache() -> None:
    """
    Intelligently sync metadata cache for teams that need it.

    This task runs periodically and only refreshes caches that:
    1. Are about to expire (within 24 hours by default)
    2. Belong to recently updated teams (within 1 hour by default)
    3. Are missing or corrupted

    This is much more efficient than refreshing all caches blindly.
    """
    from posthog.storage.team_metadata_cache import get_cache_stats, refresh_stale_caches

    logger.info("Starting intelligent team metadata cache sync")

    # Get cache statistics before refresh
    stats_before = get_cache_stats()
    logger.info(
        "Cache stats before refresh",
        total_cached=stats_before.get("total_cached", 0),
        total_teams=stats_before.get("total_teams", 0),
        coverage=stats_before.get("cache_coverage", "unknown"),
        ttl_distribution=stats_before.get("ttl_distribution", {}),
    )

    # Refresh caches that need it
    successful, failed = refresh_stale_caches(
        ttl_threshold_hours=24,  # Refresh caches expiring in next 24 hours
        recently_updated_hours=1,  # Include teams updated in last hour
        batch_size=200,  # Process up to 200 teams per run
    )

    # Get cache statistics after refresh
    stats_after = get_cache_stats()

    logger.info(
        "Completed intelligent team metadata cache sync",
        successful_refreshes=successful,
        failed_refreshes=failed,
        cache_coverage_after=stats_after.get("cache_coverage", "unknown"),
        ttl_distribution_after=stats_after.get("ttl_distribution", {}),
    )


# Django signals for real-time cache updates
@receiver(post_save, sender=Team)
def update_team_metadata_cache_on_save(sender: type[Team], instance: Team, created: bool, **kwargs: Any) -> None:
    """Update team metadata cache when a Team is saved."""

    def enqueue_task() -> None:
        try:
            update_team_metadata_cache_task.delay(instance.id)
        except Exception as e:
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
    # Clear immediately since the team is about to be deleted
    clear_team_metadata_cache(instance)
