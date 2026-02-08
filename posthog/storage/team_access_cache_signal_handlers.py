"""
Signal handler functions for team access token cache invalidation.

This module provides handler functions that automatically update
the team access token cache when Team models change,
ensuring cache consistency with the database.

Note: Signal subscriptions are registered in posthog/models/remote_config.py
Note: PersonalAPIKey and OrganizationMembership cache updates are handled
      by Celery tasks in posthog/tasks/team_access_cache_tasks.py
"""

import logging

from posthog.models.team.team import Team
from posthog.storage.team_access_cache import team_access_cache, warm_team_token_cache

logger = logging.getLogger(__name__)


def capture_old_api_token(instance: Team, **kwargs):
    """
    Capture the old api_token value before save for cleanup.

    This pre_save handler stores the old api_token value so the post_save
    handler can clean up the old cache entry when the token changes.
    """
    if instance.pk:  # Only for existing teams
        try:
            old_team = Team.objects.only("api_token").get(pk=instance.pk)
            # Store the old api_token value for post_save cleanup
            instance._old_api_token = old_team.api_token  # type: ignore[attr-defined]
        except Team.DoesNotExist:
            pass


def update_team_authentication_cache(instance: Team, created: bool, **kwargs):
    """
    Rebuild team access cache when Team model is saved.

    This handler only rebuilds the cache when authentication-related fields change
    to avoid unnecessary cache operations for unrelated team updates.
    """
    try:
        if not instance.api_token:
            return

        if created:
            logger.debug(f"New team created: {instance.pk}")
            return

        # Check if this is a new team being created
        if hasattr(instance, "_state") and instance._state.adding:
            logger.debug(f"Team {instance.pk} is being created, skipping cache update")
            return

        # Check if api_token changed (project API key regeneration)
        # We look for the old value stored before save
        old_api_token = getattr(instance, "_old_api_token", None)

        # If update_fields is specified, only rebuild cache if auth-related fields changed
        update_fields = kwargs.get("update_fields")
        auth_related_fields = {"api_token", "secret_api_token", "secret_api_token_backup"}

        if update_fields is not None:
            # Convert update_fields to set for efficient intersection
            updated_fields = set(update_fields) if update_fields else set()

            # Check if any auth-related fields were updated
            if not updated_fields.intersection(auth_related_fields):
                logger.debug(
                    f"Team {instance.pk} updated but no auth fields changed, skipping cache update",
                    extra={
                        "team_id": instance.pk,
                        "updated_fields": list(updated_fields),
                        "auth_fields": list(auth_related_fields),
                    },
                )
                return

        try:
            # Clean up old cache if api_token changed
            if old_api_token and old_api_token != instance.api_token:
                team_access_cache.invalidate_team(old_api_token)
                logger.info(
                    f"Invalidated old cache for team {instance.pk} after API token change",
                    extra={"team_id": instance.pk, "old_api_token": old_api_token, "new_api_token": instance.api_token},
                )

            warm_team_token_cache(instance.api_token)
            logger.info(
                f"Rebuilt team access cache for team {instance.pk} after auth field change",
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
