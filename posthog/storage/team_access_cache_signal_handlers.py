"""
Signal handler functions for team access token cache invalidation.

This module provides handler functions that automatically update
the team access token cache when PersonalAPIKey or Team models change,
ensuring cache consistency with the database.

Note: Signal subscriptions are registered in posthog/models/remote_config.py
"""

import logging

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.storage.team_access_cache import team_access_cache

logger = logging.getLogger(__name__)


def update_team_authentication_cache(instance: Team, created: bool, **kwargs):
    """
    Rebuild team access cache when Team model is saved.

    This handler rebuilds the cache for any team save to ensure the cache
    always reflects the latest authorized tokens. This is the most robust
    approach as it avoids state tracking and works in all deployment scenarios.
    """
    try:
        if not instance.api_token:
            return

        if created:
            # New team - no cache to rebuild yet
            logger.debug(f"New team created: {instance.pk}")
            return

        # Always rebuild cache on team save (most robust approach)
        from posthog.storage.team_access_cache import warm_team_token_cache

        try:
            warm_team_token_cache(instance.api_token)
            logger.info(
                f"Rebuilt team access cache for team {instance.pk} after save",
                extra={"team_id": instance.pk, "project_api_key": instance.api_token},
            )
        except Exception as e:
            logger.warning(
                f"Failed to rebuild cache for team {instance.pk}, falling back to invalidation: {e}",
                extra={"team_id": instance.pk},
            )
            # Fall back to invalidation if rebuild fails
            team_access_cache.invalidate_team(instance.api_token)

    except Exception as e:
        logger.exception(f"Error updating cache on team save for team {instance.pk}: {e}")


def update_team_authentication_cache_on_delete(instance: Team, **kwargs):
    """
    Invalidate team access cache when Team is deleted.
    """
    try:
        if instance.api_token:
            team_access_cache.invalidate_team(instance.api_token)
            logger.info(f"Invalidated cache for deleted team {instance.pk}")

    except Exception as e:
        logger.exception(f"Error invalidating cache on team delete for team {instance.pk}: {e}")


def update_personal_api_key_authentication_cache(instance: PersonalAPIKey, created: bool, **kwargs):
    """
    Update team access cache when PersonalAPIKey is saved.

    This handler warms the cache for all teams that the personal API key has
    access to. For unscoped keys, this includes all teams within the user's
    organizations. Since warming completely rebuilds the cache from the database,
    no prior invalidation is needed.
    """
    from posthog.storage.team_access_cache import get_teams_for_personal_api_key, warm_team_token_cache

    # Get the list of affected teams (no invalidation needed since warming rebuilds cache)
    affected_teams = get_teams_for_personal_api_key(instance)

    # Warm the cache for each affected team
    for project_api_key in affected_teams:
        try:
            warm_team_token_cache(project_api_key)
            logger.debug(f"Warmed cache for team {project_api_key} after PersonalAPIKey save")
        except Exception as e:
            logger.warning(
                f"Failed to warm cache for team {project_api_key} after PersonalAPIKey save: {e}",
                extra={"project_api_key": project_api_key, "personal_api_key_id": instance.id},
            )


def update_personal_api_key_authentication_cache_on_delete(instance: PersonalAPIKey, **kwargs):
    """
    Update team access cache when PersonalAPIKey is deleted.

    This handler warms the cache for all teams that the deleted personal API key
    had access to. For unscoped keys, this includes all teams within the user's
    organizations. Since warming completely rebuilds the cache from the database,
    no prior invalidation is needed.
    """
    from posthog.storage.team_access_cache import get_teams_for_personal_api_key, warm_team_token_cache

    # Get the list of affected teams (no invalidation needed since warming rebuilds cache)
    affected_teams = get_teams_for_personal_api_key(instance)

    # Warm the cache for each affected team
    for project_api_key in affected_teams:
        try:
            warm_team_token_cache(project_api_key)
            logger.debug(f"Warmed cache for team {project_api_key} after PersonalAPIKey delete")
        except Exception as e:
            logger.warning(
                f"Failed to warm cache for team {project_api_key} after PersonalAPIKey delete: {e}",
                extra={"project_api_key": project_api_key, "personal_api_key_id": instance.id},
            )


def update_user_authentication_cache(instance, **kwargs):
    """
    Update team access caches when a User's status changes.

    When a user is activated/deactivated, their Personal API Keys need to be
    added/removed from the authentication caches of all teams they have access to.
    This includes both scoped and unscoped keys.

    Note: The update_fields filtering is now handled by the user_saved signal handler
    in remote_config.py before calling this function.

    Args:
        sender: The model class (User)
        instance: The User instance that changed
        **kwargs: Additional signal arguments
    """
    from posthog.storage.team_access_cache import get_teams_for_personal_api_key, warm_team_token_cache

    try:
        # Get all personal API keys for this user
        personal_keys = PersonalAPIKey.objects.filter(user_id=instance.id)

        if not personal_keys.exists():
            logger.debug(f"User {instance.id} has no personal API keys, no cache updates needed")
            return

        affected_teams = set()

        # Collect all teams affected by this user's personal API keys
        for key in personal_keys:
            team_tokens = get_teams_for_personal_api_key(key)
            affected_teams.update(team_tokens)

        # Warm cache for all affected teams
        if affected_teams:
            for project_api_key in affected_teams:
                try:
                    warm_team_token_cache(project_api_key)
                    logger.debug(f"Warmed cache for team {project_api_key} after user {instance.id} status change")
                except Exception as e:
                    logger.warning(
                        f"Failed to warm cache for team {project_api_key} after user {instance.id} status change: {e}",
                        extra={"project_api_key": project_api_key, "user_id": instance.id},
                    )

            logger.info(
                f"Updated authentication cache for {len(affected_teams)} teams after user status change",
                extra={
                    "user_id": instance.id,
                    "affected_teams_count": len(affected_teams),
                    "user_is_active": instance.is_active,
                },
            )
        else:
            logger.debug(f"User {instance.id} has no accessible teams, no cache updates needed")

    except Exception as e:
        logger.exception(f"Error updating authentication cache for user {instance.id} status change: {e}")
