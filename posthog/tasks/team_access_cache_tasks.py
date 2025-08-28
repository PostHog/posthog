"""
Background tasks for warming team access token caches.

This module provides Celery tasks to periodically warm the team access token
caches, ensuring that the cached authentication system has fresh data.
"""

import logging

from django.conf import settings

from celery import shared_task
from celery.app.task import Task
from prometheus_client import Counter, Histogram

from posthog.storage.team_access_cache import get_teams_needing_cache_refresh, team_access_cache, warm_team_token_cache

logger = logging.getLogger(__name__)

# Prometheus metrics
CACHE_WARMING_OPERATIONS = Counter(
    "posthog_cache_warming_operations_total", "Number of cache warming operations", labelnames=["operation", "result"]
)

CACHE_WARMING_LATENCY = Histogram(
    "posthog_cache_warming_latency_seconds", "Latency of cache warming operations", labelnames=["operation"]
)

# Configuration
CACHE_WARMING_BATCH_SIZE = getattr(settings, "CACHE_WARMING_BATCH_SIZE", 50)
CACHE_WARMING_ENABLED = getattr(settings, "CACHE_WARMING_ENABLED", True)


@shared_task(bind=True, max_retries=3)
def warm_team_cache_task(self: "Task", project_api_key: str) -> dict:
    """
    Warm the token cache for a specific team.

    Args:
        project_api_key: The team's project API key

    Returns:
        Dictionary with operation results
    """
    with CACHE_WARMING_LATENCY.labels(operation="single_team").time():
        success = warm_team_token_cache(project_api_key)

        if not success:
            CACHE_WARMING_OPERATIONS.labels(operation="single_team", result="error").inc()
            logger.warning(f"Failed to warm cache for team {project_api_key}")
            # Retry with exponential backoff
            raise self.retry(countdown=60 * (2**self.request.retries))

        # Get token count for monitoring
        token_count = team_access_cache.get_cached_token_count(project_api_key)

        CACHE_WARMING_OPERATIONS.labels(operation="single_team", result="success").inc()

        logger.info(
            f"Successfully warmed cache for team {project_api_key}",
            extra={"project_api_key": project_api_key, "token_count": token_count},
        )

        return {"status": "success", "project_api_key": project_api_key, "token_count": token_count}


@shared_task(bind=True, max_retries=1)
def warm_all_teams_caches_task(self: "Task") -> dict:
    """
    Warm caches for all teams that need refreshing.

    This task identifies teams with expired or missing caches and
    schedules individual warming tasks for each team.

    Returns:
        Dictionary with operation results
    """
    if not CACHE_WARMING_ENABLED:
        logger.info("Cache warming is disabled")
        return {"status": "disabled"}

    with CACHE_WARMING_LATENCY.labels(operation="all_teams").time():
        try:
            # Get teams needing cache refresh - may raise exceptions for systemic issues
            teams_needing_refresh = get_teams_needing_cache_refresh()

            if not teams_needing_refresh:
                logger.info("No teams need cache refresh")
                CACHE_WARMING_OPERATIONS.labels(operation="all_teams", result="no_work").inc()
                return {"status": "success", "teams_refreshed": 0, "message": "No teams needed refresh"}

            logger.info(
                f"Found {len(teams_needing_refresh)} teams needing cache refresh",
                extra={"team_count": len(teams_needing_refresh)},
            )

            # Process teams in batches to avoid overwhelming the system
            teams_scheduled = 0
            failed_teams = 0

            for i in range(0, len(teams_needing_refresh), CACHE_WARMING_BATCH_SIZE):
                batch = teams_needing_refresh[i : i + CACHE_WARMING_BATCH_SIZE]

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

            # Log results
            if failed_teams > 0:
                logger.warning(
                    f"Cache warming scheduled for {teams_scheduled} teams, {failed_teams} failed to schedule",
                    extra={"teams_scheduled": teams_scheduled, "failed_teams": failed_teams},
                )
                CACHE_WARMING_OPERATIONS.labels(operation="all_teams", result="partial_success").inc()
            else:
                CACHE_WARMING_OPERATIONS.labels(operation="all_teams", result="success").inc()

            logger.info(
                f"Scheduled cache warming for {teams_scheduled} teams",
                extra={"teams_scheduled": teams_scheduled, "failed_teams": failed_teams},
            )

            return {
                "status": "success",
                "teams_found": len(teams_needing_refresh),
                "teams_scheduled": teams_scheduled,
                "failed_teams": failed_teams,
            }

        except Exception as e:
            # Retry for systemic failures (database connectivity, etc.)
            CACHE_WARMING_OPERATIONS.labels(operation="all_teams", result="error").inc()
            logger.exception(f"Systemic failure in cache warming batch task: {e}")
            raise self.retry(exc=e, countdown=300)  # 5 minutes
