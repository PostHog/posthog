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

from posthog.models.team import Team
from posthog.storage.team_metadata_cache import (
    TEAM_METADATA_BATCH_REFRESH_COUNTER,
    TEAM_METADATA_BATCH_REFRESH_DURATION_HISTOGRAM,
    TEAM_METADATA_CACHE_COVERAGE_GAUGE,
    TEAM_METADATA_TEAMS_PROCESSED_COUNTER,
    clear_team_metadata_cache,
    get_cache_stats,
    refresh_stale_caches,
    update_team_metadata_cache,
)
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
        logger.debug("Team does not exist for metadata cache update", team_id=team_id)
        return

    update_team_metadata_cache(team)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_stale_team_metadata_cache() -> None:
    """
    Intelligently sync metadata cache for teams that need it.

    This task runs periodically and only refreshes caches that:
    1. Are about to expire (within 24 hours by default)
    2. Are missing for active teams

    Note: Recently updated teams are handled by Django signals automatically,
    so they don't need to be included here.
    """

    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping team metadata cache refresh")
        return

    start_time = time.time()
    logger.info("Starting intelligent team metadata cache sync")

    try:
        stats_before = get_cache_stats()
        logger.info(
            "Team metadata cache stats before refresh",
            total_cached=stats_before.get("total_cached", 0),
            total_teams=stats_before.get("total_teams", 0),
            coverage=stats_before.get("cache_coverage", "unknown"),
            ttl_distribution=stats_before.get("ttl_distribution", {}),
        )

        successful, failed = refresh_stale_caches(
            ttl_threshold_hours=24,
            batch_size=200,
        )

        TEAM_METADATA_TEAMS_PROCESSED_COUNTER.labels(result="success").inc(successful)
        TEAM_METADATA_TEAMS_PROCESSED_COUNTER.labels(result="failed").inc(failed)

        stats_after = get_cache_stats()

        coverage_percent = stats_after.get("cache_coverage_percent", 0)
        TEAM_METADATA_CACHE_COVERAGE_GAUGE.set(coverage_percent)

        duration = time.time() - start_time
        TEAM_METADATA_BATCH_REFRESH_DURATION_HISTOGRAM.observe(duration)
        TEAM_METADATA_BATCH_REFRESH_COUNTER.labels(result="success").inc()

        logger.info(
            "Completed team metadata cache refresh",
            successful_refreshes=successful,
            failed_refreshes=failed,
            cache_coverage_after=stats_after.get("cache_coverage", "unknown"),
            ttl_distribution_after=stats_after.get("ttl_distribution", {}),
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        TEAM_METADATA_BATCH_REFRESH_DURATION_HISTOGRAM.observe(duration)
        TEAM_METADATA_BATCH_REFRESH_COUNTER.labels(result="failed").inc()
        logger.exception(
            "Failed to complete team metadata batch refresh",
            error=str(e),
            duration_seconds=duration,
        )
        raise


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
    # NB: For unit tests, only clear Redis to avoid S3 timestamp issues with frozen time
    kinds = ["redis"] if settings.TEST else None
    clear_team_metadata_cache(instance, kinds=kinds)
