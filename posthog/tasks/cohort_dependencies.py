from collections.abc import Generator
from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from celery import chain, shared_task
from celery.app.task import Task
from prometheus_client import Gauge
from structlog import get_logger

from posthog.models.cohort.dependencies import warm_team_cohort_dependency_cache
from posthog.models.team.team import Team

logger = get_logger(__name__)

# Configuration
COHORT_CACHE_WARMING_BATCH_SIZE = getattr(settings, "COHORT_CACHE_WARMING_BATCH_SIZE", 50)
COHORT_CACHE_WARMING_PAGE_SIZE = getattr(settings, "COHORT_CACHE_WARMING_PAGE_SIZE", 1000)
COHORT_CACHE_WARMING_MIN_COHORTS = getattr(settings, "COHORT_CACHE_WARMING_MIN_COHORTS", 50)
COHORT_CACHE_WARMING_ACTIVE_CHAINS = Gauge(
    "posthog_cohort_cache_warming_active_chains", "Number of currently active cohort cache warming chains"
)


@shared_task(bind=True, max_retries=1)
def warm_cohort_dependencies_cache_for_all_teams(self: "Task") -> dict:
    """
    Warm the cohort dependencies cache for teams with many cohorts.

    This task identifies teams with many cohorts (>= min threshold) and schedules individual
    warming tasks for each team to avoid overwhelming the system.

    Returns:
        Dictionary with operation results
    """
    try:
        teams_scheduled = 0
        failed_teams = 0
        teams_pages_processed = 0
        total_teams_found = 0

        logger.info(
            "Warming cohort dependencies cache",
            page_size=COHORT_CACHE_WARMING_PAGE_SIZE,
            min_cohorts=COHORT_CACHE_WARMING_MIN_COHORTS,
        )

        # Process teams in pages for memory efficiency
        for teams_page in _get_teams_with_cohorts_paginated(batch_size=COHORT_CACHE_WARMING_PAGE_SIZE):
            teams_pages_processed += 1

            if not teams_page:
                continue

            total_teams_found += len(teams_page)

            logger.debug(
                "Processing page of teams for cohort cache warming",
                page=teams_pages_processed,
                total_teams_found=total_teams_found,
                teams_in_page=len(teams_page),
            )

            for i in range(0, len(teams_page), COHORT_CACHE_WARMING_BATCH_SIZE):
                batch = teams_page[i : i + COHORT_CACHE_WARMING_BATCH_SIZE]

                # Create a chain for this batch (sequential execution)
                # Add all team warming tasks, then add a gauge decrement task at the end
                # Warming the cohort cache isn't super compute or database intensive, but
                # splitting into serialized chains seems like a good way to prevent emitting
                # too many tasks at once.
                chain_tasks = [warm_cohort_dependencies_cache_for_team.si(team_id) for team_id in batch]
                chain_tasks.append(decrement_active_chains_gauge.si())

                try:
                    # Set expiration time for the chain
                    expire_after = timezone.now() + timedelta(minutes=30)
                    chain(*chain_tasks).apply_async(expires=expire_after)
                    teams_scheduled += len(batch)
                    COHORT_CACHE_WARMING_ACTIVE_CHAINS.inc()

                    logger.debug("Scheduled chain for batch", batch_size=len(batch), teams_in_batch=batch)
                except Exception as e:
                    # Log batch scheduling failure but continue with others
                    failed_teams += len(batch)
                    logger.exception(
                        "Failed to schedule chain for batch",
                        batch_size=len(batch),
                        error=str(e),
                    )

        logger.info(
            "Cohort cache warming completed",
            teams_found=total_teams_found,
            teams_scheduled=teams_scheduled,
            failed_teams=failed_teams,
        )

        return {
            "status": "success",
            "teams_found": total_teams_found,
            "teams_scheduled": teams_scheduled,
            "failed_teams": failed_teams,
        }

    except Exception as e:
        logger.exception("Failure in cohort cache warming batch task", error=e)
        raise self.retry(exc=e, countdown=300)  # 5 minutes


@shared_task(bind=True, max_retries=3)
def warm_cohort_dependencies_cache_for_team(self: "Task", team_id: int) -> dict:
    """
    Warm the cohort dependencies cache for a specific team.

    Args:
        team_id: The team's ID

    Returns:
        Dictionary with operation results
    """
    try:
        warm_team_cohort_dependency_cache(team_id)
        return {"status": "success", "team_id": team_id}

    except Exception as e:
        # Log a warning, but don't retry immediately. We'll let the next scheduled task pick it up.
        logger.warning("Failed to warm cohort dependencies cache for team", team_id=team_id, error=e)
        return {"status": "failure", "team_id": team_id}


@shared_task(bind=True, max_retries=0)
def decrement_active_chains_gauge(self: "Task") -> dict:
    """
    Decrement the active chains gauge when a chain completes.
    """
    COHORT_CACHE_WARMING_ACTIVE_CHAINS.dec()
    return {"status": "success"}


def _get_teams_with_cohorts_paginated(batch_size: int = 1000) -> Generator[list[int], None, None]:
    """
    Generator that yields batches of team IDs that have many cohorts (>= min threshold).

    Args:
        batch_size: Number of teams to process per batch

    Yields:
        List[int]: Batches of team IDs that have many cohorts
    """
    offset = 0

    while True:
        # Get teams with many cohorts (>= min threshold), ordered by ID for consistent pagination
        teams_batch = list(
            Team.objects.filter(cohort__deleted=False)
            .annotate(cohort_count=Count("cohort"))
            .filter(cohort_count__gte=COHORT_CACHE_WARMING_MIN_COHORTS)
            .order_by("id")
            .values_list("id", flat=True)[offset : offset + batch_size]
        )

        if not teams_batch:
            # No more teams to process
            break

        yield teams_batch
        offset += batch_size

        # If we got fewer teams than requested, we've reached the end
        if len(teams_batch) < batch_size:
            break
