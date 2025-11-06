"""
Celery tasks for team metadata cache management.

Provides async tasks for updating and syncing team metadata caches.
"""

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
            team_api_token=team.api_token,
        )
    else:
        logger.error(
            "Failed to update team metadata cache",
            team_id=team_id,
            team_api_token=team.api_token,
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

    # Get total count for logging
    total_count = Team.objects.count()
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
                    team_api_token=team.api_token,
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
def update_team_metadata_cache_batch(self, team_ids: list[int]) -> None:
    """
    Update metadata cache for a batch of teams.

    This task processes multiple teams in a single job, useful for
    bulk operations or when many teams need updating at once.

    Args:
        team_ids: List of team IDs to update
    """
    logger.info(f"Starting batch update of {len(team_ids)} team metadata caches")

    successful_updates = 0
    failed_updates = 0

    for team_id in team_ids:
        try:
            team = Team.objects.get(id=team_id)
            success = update_team_metadata_cache(team)

            if success:
                successful_updates += 1
            else:
                failed_updates += 1
                logger.warning(
                    "Failed to update team metadata cache in batch",
                    team_id=team_id,
                )

        except Team.DoesNotExist:
            failed_updates += 1
            logger.warning(
                "Team not found for batch metadata cache update",
                team_id=team_id,
            )
        except Exception as e:
            failed_updates += 1
            logger.exception(
                "Error in batch team metadata cache update",
                team_id=team_id,
                exception=str(e),
            )

    logger.info(
        "Completed batch update of team metadata caches",
        total=len(team_ids),
        successful=successful_updates,
        failed=failed_updates,
    )

    # Retry if there were failures
    if failed_updates > 0 and self.request.retries < self.max_retries:
        # Get the IDs that failed for retry - more efficient bulk query
        failed_ids = []
        teams_to_check = Team.objects.filter(id__in=team_ids).only("id", "api_token")

        for team in teams_to_check:
            try:
                from posthog.storage.team_metadata_cache import get_team_metadata

                if get_team_metadata(team) is None:
                    failed_ids.append(team.id)
            except Exception as e:
                logger.warning(f"Error checking cache for team {team.id}: {e}")
                failed_ids.append(team.id)

        if failed_ids:
            logger.info(
                f"Retrying {len(failed_ids)} failed team metadata cache updates",
                retry_count=self.request.retries + 1,
            )
            raise self.retry(args=[failed_ids], countdown=60)  # Retry after 1 minute


# Django signals for real-time cache updates
@receiver(post_save, sender=Team)
def update_team_metadata_cache_on_save(sender, instance: Team, created: bool, **kwargs):
    """Update team metadata cache when a Team is saved."""
    # Use transaction.on_commit to ensure the database changes are committed
    # before we update the cache
    transaction.on_commit(lambda: update_team_metadata_cache_task.delay(instance.id))


@receiver(pre_delete, sender=Team)
def clear_team_metadata_cache_on_delete(sender, instance: Team, **kwargs):
    """Clear team metadata cache when a Team is deleted."""
    # Clear immediately since the team is about to be deleted
    clear_team_metadata_cache(instance)
