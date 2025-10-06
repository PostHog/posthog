"""
Background tasks for warming team access token caches.

This module provides Celery tasks to periodically warm the team access token
caches, ensuring that the cached authentication system has fresh data.
"""

import logging

from django.conf import settings

from celery import shared_task
from celery.app.task import Task

from posthog.storage.team_access_cache import get_teams_needing_cache_refresh_paginated, warm_team_token_cache

logger = logging.getLogger(__name__)

# Configuration
CACHE_WARMING_BATCH_SIZE = getattr(settings, "CACHE_WARMING_BATCH_SIZE", 50)
CACHE_WARMING_PAGE_SIZE = getattr(settings, "CACHE_WARMING_PAGE_SIZE", 1000)  # Teams per database page


@shared_task(bind=True, max_retries=3)
def warm_team_cache_task(self: "Task", project_api_key: str) -> dict:
    """
    Warm the token cache for a specific team.

    Args:
        project_api_key: The team's project API key

    Returns:
        Dictionary with operation results
    """
    success = warm_team_token_cache(project_api_key)

    if not success:
        # Log a warning, but don't retry. We'll let the next scheduled task pick it up.
        logger.warning(f"Failed to warm cache for team {project_api_key}")
        return {"status": "failure", "project_api_key": project_api_key}

    logger.info(
        f"Successfully warmed cache for team {project_api_key}",
        extra={"project_api_key": project_api_key},
    )

    return {"status": "success", "project_api_key": project_api_key}


@shared_task(bind=True, max_retries=1)
def warm_all_team_access_caches_task(self: "Task") -> dict:
    """
    Warm caches for all teams that need refreshing.

    This task identifies teams with expired or missing caches and
    schedules individual warming tasks for each team.

    Returns:
        Dictionary with operation results
    """
    try:
        teams_scheduled = 0
        failed_teams = 0
        teams_pages_processed = 0
        total_teams_found = 0

        # Use paginated approach for memory efficiency
        logger.info(f"Using paginated cache warming with page size {CACHE_WARMING_PAGE_SIZE}")

        for teams_page in get_teams_needing_cache_refresh_paginated(batch_size=CACHE_WARMING_PAGE_SIZE):
            teams_pages_processed += 1

            if not teams_page:
                continue

            total_teams_found += len(teams_page)

            logger.debug(
                f"Processing page {teams_pages_processed} with {len(teams_page)} teams needing refresh",
                extra={"page": teams_pages_processed, "teams_in_page": len(teams_page)},
            )

            # Process teams in batches to avoid overwhelming the system
            for i in range(0, len(teams_page), CACHE_WARMING_BATCH_SIZE):
                batch = teams_page[i : i + CACHE_WARMING_BATCH_SIZE]

                # Schedule warming tasks for this batch
                for project_api_key in batch:
                    try:
                        warm_team_cache_task.delay(project_api_key)
                        teams_scheduled += 1
                    except Exception as e:
                        # Log individual team scheduling failure but continue with others
                        failed_teams += 1
                        logger.warning(
                            f"Failed to schedule cache warming for team {project_api_key}: {e}",
                            extra={"project_api_key": project_api_key, "error": str(e)},
                        )

                logger.debug(f"Scheduled cache warming for batch of {len(batch)} teams")

        logger.info(
            "Cache warming completed",
            extra={"teams_found": total_teams_found, "teams_scheduled": teams_scheduled, "failed_teams": failed_teams},
        )

        return {
            "status": "success",
            "teams_found": total_teams_found,
            "teams_scheduled": teams_scheduled,
            "failed_teams": failed_teams,
        }

    except Exception as e:
        # Retry for systemic failures (database connectivity, etc.)
        logger.exception(f"Systemic failure in cache warming batch task: {e}")
        raise self.retry(exc=e, countdown=300)  # 5 minutes
