"""
Signal handler functions for team access token cache invalidation.

This module provides handler functions that automatically update
the team access token cache when PersonalAPIKey or Team models change,
ensuring cache consistency with the database.

Note: Signal subscriptions are registered in posthog/models/remote_config.py
"""

import logging

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.storage.team_access_cache import (
    get_teams_for_user_personal_api_keys,
    team_access_cache,
    warm_team_token_cache,
)

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


def update_personal_api_key_authentication_cache(instance: PersonalAPIKey):
    """
    Update team access cache when PersonalAPIKey is saved.

    This handler warms the cache for all teams that the user's personal API keys have
    access to. For optimal performance, it uses the user-based function to warm all
    affected teams at once. Since warming completely rebuilds the cache from the database,
    no prior invalidation is needed.
    """
    # Get the list of affected teams using optimized user-based function
    affected_teams = get_teams_for_user_personal_api_keys(instance.user_id)

    # Warm the cache for each affected team
    for project_api_key in affected_teams:
        try:
            warm_team_token_cache(project_api_key)
            logger.debug(f"Warmed cache for team {project_api_key} after PersonalAPIKey change")
        except Exception as e:
            logger.warning(
                f"Failed to warm cache for team {project_api_key} after PersonalAPIKey change: {e}",
                extra={"project_api_key": project_api_key, "personal_api_key_id": instance.id},
            )

    logger.info(
        f"Updated authentication cache for {len(affected_teams)} teams after PersonalAPIKey change",
        extra={"personal_api_key_id": instance.id, "affected_teams_count": len(affected_teams)},
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
    try:
        # Get all teams that the user's personal API keys have access to
        affected_teams = get_teams_for_user_personal_api_keys(instance.id)

        _warm_cache_for_teams(affected_teams, "user status change", str(instance.id), None)

    except Exception as e:
        logger.exception(f"Error updating authentication cache for user {instance.id} status change: {e}")


def update_personal_api_key_deleted_cache(instance: PersonalAPIKey):
    """
    Update team access caches when a PersonalAPIKey is deleted.

    When a PersonalAPIKey is deleted, it needs to be removed from all team caches
    that it had access to. This includes both scoped and unscoped keys.

    Args:
        instance: The PersonalAPIKey instance that was deleted
    """
    try:
        # Get all teams that this specific key had access to
        # We need to determine this based on the key's scoping
        scoped_teams = instance.scoped_teams or []

        if scoped_teams:
            # Scoped key - only affects specific teams
            team_api_tokens = Team.objects.filter(id__in=scoped_teams).values_list("api_token", flat=True)
        else:
            # Unscoped key - affects all teams in user's organizations
            user_organizations = OrganizationMembership.objects.filter(user_id=instance.user_id).values_list(
                "organization_id", flat=True
            )

            if user_organizations:
                team_api_tokens = Team.objects.filter(organization_id__in=user_organizations).values_list(
                    "api_token", flat=True
                )
            else:
                team_api_tokens = []

        _warm_cache_for_teams(team_api_tokens, "PersonalAPIKey deletion", str(instance.user_id), None)

    except Exception as e:
        logger.exception(
            f"Error updating team caches after PersonalAPIKey deletion: {e}",
            extra={
                "personal_api_key_id": getattr(instance, "id", None),
                "user_id": getattr(instance, "user_id", None),
            },
        )


def update_organization_membership_created_cache(membership_instance):
    """
    Update team access caches when an OrganizationMembership is created.

    When a user is added to an organization, their unscoped Personal API Keys should
    gain access to teams within that organization. This function updates the caches for
    all teams in the organization that was joined.

    Args:
        membership_instance: The OrganizationMembership instance that was created
    """
    try:
        # Get all teams in the organization the user joined
        organization_id = membership_instance.organization_id
        user_id = membership_instance.user_id

        team_api_tokens = Team.objects.filter(organization_id=organization_id).values_list("api_token", flat=True)

        _warm_cache_for_teams(team_api_tokens, "adding user to organization", user_id, organization_id)

    except Exception as e:
        logger.exception(
            f"Error updating team caches after OrganizationMembership creation: {e}",
            extra={
                "user_id": getattr(membership_instance, "user_id", None),
                "organization_id": getattr(membership_instance, "organization_id", None),
            },
        )


def update_organization_membership_deleted_cache(membership_instance):
    """
    Update team access caches when an OrganizationMembership is deleted.

    When a user is removed from an organization, their Personal API Keys should no longer
    have access to teams within that organization. This function updates the caches for
    all teams in the organization that was removed from.

    This is different from update_user_authentication_cache because we need to update
    the teams from the organization the user was REMOVED from, not their current teams
    (which won't include the removed organization anymore).

    Args:
        membership_instance: The OrganizationMembership instance that was deleted
    """
    try:
        # Get all teams in the organization the user was removed from
        organization_id = membership_instance.organization_id
        user_id = membership_instance.user_id

        team_api_tokens = Team.objects.filter(organization_id=organization_id).values_list("api_token", flat=True)

        _warm_cache_for_teams(team_api_tokens, "removing user from organization", user_id, organization_id)

    except Exception as e:
        logger.exception(
            f"Error updating team caches after OrganizationMembership deletion: {e}",
            extra={
                "user_id": getattr(membership_instance, "user_id", None),
                "organization_id": getattr(membership_instance, "organization_id", None),
            },
        )


def _warm_cache_for_teams(
    team_api_tokens: set[str] | list[str], action: str, user_id: str, organization_id: str | None
):
    """
    Warm the cache for a set of teams.
    """
    if not team_api_tokens:
        logger.debug(f"No teams found in organization {organization_id}, no cache updates needed")
        return

    # Warm the cache for each team in the organization
    # This will rebuild the cache without the removed user's keys
    for project_api_key in team_api_tokens:
        try:
            warm_team_token_cache(project_api_key)
            logger.debug(
                f"Warmed cache for team {project_api_key} after {action}",
                extra={
                    "project_api_key": project_api_key,
                    "user_id": user_id,
                    "organization_id": organization_id,
                },
            )
        except Exception as e:
            logger.warning(
                f"Failed to warm cache for team {project_api_key} after {action}: {e}",
                extra={
                    "project_api_key": project_api_key,
                    "user_id": user_id,
                    "organization_id": organization_id,
                },
            )

    logger.info(
        f"Updated {len(team_api_tokens)} team caches after {action}",
        extra={
            "user_id": user_id,
            "organization_id": organization_id,
            "teams_updated": len(team_api_tokens),
        },
    )
