"""
Background tasks for warming team access token caches.

This module provides Celery tasks to periodically warm the team access token
caches, ensuring that the cached authentication system has fresh data.
"""

import logging
from collections.abc import Iterable

from django.conf import settings

from celery import shared_task
from celery.app.task import Task

from posthog.storage.team_access_cache import (
    get_teams_for_user_personal_api_keys,
    get_teams_needing_cache_refresh_paginated,
    warm_team_token_cache,
)

logger = logging.getLogger(__name__)

# Configuration
CACHE_WARMING_BATCH_SIZE = getattr(settings, "CACHE_WARMING_BATCH_SIZE", 50)
CACHE_WARMING_PAGE_SIZE = getattr(settings, "CACHE_WARMING_PAGE_SIZE", 1000)  # Teams per database page


def _warm_team_caches(team_api_tokens: Iterable[str], reason: str, log_context: dict) -> int:
    """
    Warm caches for a list of teams.

    Args:
        team_api_tokens: List of project API keys to warm caches for
        reason: Description for logging (e.g., "user activation", "PersonalAPIKey deletion")
        log_context: Additional context to include in log messages

    Returns:
        Number of teams successfully updated
    """
    teams_updated = 0
    for project_api_key in team_api_tokens:
        try:
            warm_team_token_cache(project_api_key)
            teams_updated += 1
            logger.debug(
                f"Warmed cache for team after {reason}",
                extra={"project_api_key": project_api_key, **log_context},
            )
        except Exception as e:
            logger.warning(
                f"Failed to warm cache for team after {reason}: {e}",
                extra={"project_api_key": project_api_key, **log_context},
            )
    return teams_updated


def _warm_teams_for_user(user_id: int, reason: str) -> dict:
    """
    Shared implementation for warming team caches based on a user's access.

    This helper consolidates the cache warming logic used by multiple tasks
    that need to update caches for all teams a user has access to.

    Args:
        user_id: The user's database ID
        reason: Description for logging (e.g., "user status change", "PersonalAPIKey change")

    Returns:
        Dictionary with operation results including status, user_id, and teams_updated count
    """
    try:
        affected_teams = get_teams_for_user_personal_api_keys(user_id)

        if not affected_teams:
            logger.debug(f"No teams found for user {user_id}, no cache updates needed")
            return {"status": "success", "user_id": user_id, "teams_updated": 0}

        teams_updated = _warm_team_caches(affected_teams, reason, {"user_id": user_id})

        logger.info(
            f"Updated {teams_updated} team caches after {reason}",
            extra={"user_id": user_id, "teams_updated": teams_updated},
        )

        return {"status": "success", "user_id": user_id, "teams_updated": teams_updated}

    except Exception as e:
        logger.exception(f"Error updating authentication cache for user {user_id} after {reason}: {e}")
        return {"status": "failure", "user_id": user_id, "error": str(e)}


def warm_user_teams_cache_sync(user_id: int) -> dict:
    """
    Synchronously warm the token cache for all teams a user has access to.

    This function is used when immediate cache invalidation is required,
    such as when a user is deactivated (security-critical operation).

    Args:
        user_id: The user's database ID

    Returns:
        Dictionary with operation results
    """
    return _warm_teams_for_user(user_id, "user deactivation")


@shared_task(bind=True, max_retries=3)
def warm_user_teams_cache_task(self: "Task", user_id: int) -> dict:
    """
    Warm the token cache for all teams a user has access to.

    This task is triggered when a user is activated, ensuring their
    Personal API Keys are properly added to team caches.

    Args:
        user_id: The user's database ID

    Returns:
        Dictionary with operation results
    """
    return _warm_teams_for_user(user_id, "user activation")


@shared_task(bind=True, max_retries=3)
def warm_personal_api_key_teams_cache_task(self: "Task", user_id: int) -> dict:
    """
    Warm the token cache for all teams a user's personal API keys have access to.

    This task is triggered when a PersonalAPIKey is created or updated, ensuring
    the team caches reflect the current state of the user's API keys.

    Args:
        user_id: The user's database ID

    Returns:
        Dictionary with operation results
    """
    return _warm_teams_for_user(user_id, "PersonalAPIKey change")


@shared_task(bind=True, max_retries=3)
def warm_personal_api_key_deleted_cache_task(self: "Task", user_id: int, scoped_team_ids: list[int] | None) -> dict:
    """
    Warm the token cache for teams after a PersonalAPIKey is deleted.

    This task is triggered when a PersonalAPIKey is deleted. We need to warm
    the caches for all teams that the deleted key had access to.

    Args:
        user_id: The user's database ID
        scoped_team_ids: List of team IDs the key was scoped to, or None if unscoped

    Returns:
        Dictionary with operation results
    """
    from posthog.models.organization import OrganizationMembership
    from posthog.models.team.team import Team

    try:
        if scoped_team_ids:
            # Scoped key - only affects specific teams
            team_api_tokens = list(Team.objects.filter(id__in=scoped_team_ids).values_list("api_token", flat=True))
        else:
            # Unscoped key - affects all teams in user's organizations
            user_organizations = list(
                OrganizationMembership.objects.filter(user_id=user_id).values_list("organization_id", flat=True)
            )

            if user_organizations:
                team_api_tokens = list(
                    Team.objects.filter(organization_id__in=user_organizations).values_list("api_token", flat=True)
                )
            else:
                team_api_tokens = []

        if not team_api_tokens:
            logger.debug(f"No teams found for deleted PersonalAPIKey (user {user_id}), no cache updates needed")
            return {"status": "success", "user_id": user_id, "teams_updated": 0}

        teams_updated = _warm_team_caches(team_api_tokens, "PersonalAPIKey deletion", {"user_id": user_id})

        logger.info(
            f"Updated {teams_updated} team caches after PersonalAPIKey deletion",
            extra={"user_id": user_id, "teams_updated": teams_updated},
        )

        return {"status": "success", "user_id": user_id, "teams_updated": teams_updated}

    except Exception as e:
        logger.exception(f"Error updating authentication cache after PersonalAPIKey deletion for user {user_id}: {e}")
        return {"status": "failure", "user_id": user_id, "error": str(e)}


@shared_task(bind=True, max_retries=3)
def warm_organization_teams_cache_task(self: "Task", organization_id: str, user_id: int, action: str) -> dict:
    """
    Warm the token cache for all teams in an organization.

    This task is triggered when a user is added to or removed from an organization,
    ensuring team caches reflect the current membership state.

    Args:
        organization_id: The organization's ID
        user_id: The user's database ID (for logging)
        action: Description of the action (e.g., "added to organization", "removed from organization")

    Returns:
        Dictionary with operation results
    """
    from posthog.models.team.team import Team

    try:
        team_api_tokens = list(Team.objects.filter(organization_id=organization_id).values_list("api_token", flat=True))

        if not team_api_tokens:
            logger.debug(f"No teams found in organization {organization_id}, no cache updates needed")
            return {"status": "success", "organization_id": organization_id, "user_id": user_id, "teams_updated": 0}

        log_context = {"user_id": user_id, "organization_id": organization_id}
        teams_updated = _warm_team_caches(team_api_tokens, f"user {action}", log_context)

        logger.info(
            f"Updated {teams_updated} team caches after user {action}",
            extra={"user_id": user_id, "organization_id": organization_id, "teams_updated": teams_updated},
        )

        return {
            "status": "success",
            "organization_id": organization_id,
            "user_id": user_id,
            "teams_updated": teams_updated,
        }

    except Exception as e:
        logger.exception(
            f"Error updating authentication cache after user {action} for organization {organization_id}: {e}"
        )
        return {"status": "failure", "organization_id": organization_id, "user_id": user_id, "error": str(e)}


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
