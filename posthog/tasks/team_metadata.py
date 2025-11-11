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
def sync_all_team_metadata_cache() -> None:
    """
    Sync metadata cache for all teams.

    This task is meant to be run periodically (e.g., hourly) to ensure
    all team metadata caches are fresh. It processes teams in batches
    to avoid overwhelming the system.
    """
    logger.info("Starting sync of all team metadata caches")

    total_teams = 0
    successful_updates = 0
    failed_updates = 0

    # Process teams in batches to avoid memory issues
    batch_size = 100

    # Get approximate count for logging - use only('id') to reduce overhead
    total_count = Team.objects.only("id").count()
    logger.info(f"Total teams to sync: {total_count}")

    # Process in batches using iterator for memory efficiency
    for team in Team.objects.iterator(chunk_size=batch_size):
        total_teams += 1

        try:
            # Update cache for this team
            success = update_team_metadata_cache(team)

            if success:
                successful_updates += 1
            else:
                failed_updates += 1
                logger.warning(
                    "Failed to sync team metadata cache",
                    team_id=team.id,
                )

        except Exception as e:
            failed_updates += 1
            logger.exception(
                "Error syncing team metadata cache",
                team_id=team.id,
                exception=str(e),
            )

        # Log progress every 100 teams
        if total_teams % 100 == 0:
            logger.info(
                "Team metadata cache sync progress",
                processed=total_teams,
                total=total_count,
                successful=successful_updates,
                failed=failed_updates,
            )

    logger.info(
        "Completed sync of all team metadata caches",
        total_teams=total_teams,
        successful_updates=successful_updates,
        failed_updates=failed_updates,
    )


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value, bind=True, max_retries=3)
def update_team_metadata_cache_batch(self: shared_task, team_ids: list[int]) -> None:
    """
    Update metadata cache for a batch of teams.

    This task processes multiple teams in a single job, useful for
    bulk operations or when many teams need updating at once.

    Args:
        team_ids: List of team IDs to update
    """
    logger.info(f"Starting batch update of {len(team_ids)} team metadata caches")

    successful_updates = 0
    failed_ids = []  # Track failures immediately during initial run

    for team_id in team_ids:
        try:
            team = Team.objects.get(id=team_id)
            success = update_team_metadata_cache(team)

            if success:
                successful_updates += 1
            else:
                failed_ids.append(team_id)  # Track failure immediately
                logger.warning(
                    "Failed to update team metadata cache in batch",
                    team_id=team_id,
                )

        except Team.DoesNotExist:
            failed_ids.append(team_id)  # Track failure immediately
            logger.warning(
                "Team not found for batch metadata cache update",
                team_id=team_id,
            )
        except Exception as e:
            failed_ids.append(team_id)  # Track failure immediately
            logger.exception(
                "Error in batch team metadata cache update",
                team_id=team_id,
                exception=str(e),
            )

    logger.info(
        "Completed batch update of team metadata caches",
        total=len(team_ids),
        successful=successful_updates,
        failed=len(failed_ids),
    )

    # Retry if there were failures
    if failed_ids and self.request.retries < self.max_retries:
        logger.info(
            f"Retrying {len(failed_ids)} failed team metadata cache updates",
            retry_count=self.request.retries + 1,
        )
        raise self.retry(args=[failed_ids], countdown=60)  # Retry after 1 minute


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sync_team_metadata_cache_intelligent() -> None:
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
