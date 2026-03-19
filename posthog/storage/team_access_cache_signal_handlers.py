"""
Signal handlers for team access token cache invalidation.

This module registers @receiver signal handlers that automatically update
the team access token cache when Team, PersonalAPIKey, User, and
OrganizationMembership models change, ensuring cache consistency with the database.

Celery task implementations live in posthog/tasks/team_access_cache_tasks.py.
"""

import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch.dispatcher import receiver

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.storage.team_access_cache import team_access_cache, warm_team_token_cache

logger = logging.getLogger(__name__)


# --- Team signal handlers ---


def _capture_old_api_token(instance: Team, **kwargs):
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


@receiver(pre_save, sender=Team)
def team_pre_save_auth_cache(sender, instance: "Team", **kwargs):
    """Capture old api_token value before save for cache cleanup."""
    _capture_old_api_token(instance, **kwargs)


@receiver(post_save, sender=Team)
def team_saved_auth_cache(sender, instance: "Team", created, **kwargs):
    """Update team authentication cache on team save."""
    transaction.on_commit(lambda: _update_team_authentication_cache(instance, created, **kwargs))


@receiver(post_delete, sender=Team)
def team_deleted_auth_cache(sender, instance: "Team", **kwargs):
    """Handle team deletion for access cache."""
    transaction.on_commit(lambda: _update_team_authentication_cache_on_delete(instance, **kwargs))


def _update_team_authentication_cache(instance: Team, created: bool, **kwargs):
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

        # Check if api_token changed (project token regeneration)
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


def _update_team_authentication_cache_on_delete(instance: Team, **kwargs):
    """
    Invalidate team access cache when Team is deleted.
    """
    try:
        if instance.api_token:
            team_access_cache.invalidate_team(instance.api_token)
            logger.info(f"Invalidated cache for deleted team {instance.pk}")

    except Exception as e:
        logger.exception(f"Error invalidating cache on team delete for team {instance.pk}: {e}")


# --- PersonalAPIKey signal handlers ---


@receiver(post_save, sender=PersonalAPIKey)
def personal_api_key_saved(sender, instance: "PersonalAPIKey", created, **kwargs):
    """
    Handle PersonalAPIKey save for team access cache invalidation.

    Skip cache updates for last_used_at field updates to avoid unnecessary cache warming
    during authentication requests.
    """
    # Skip cache updates if only last_used_at is being updated
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and set(update_fields) == {"last_used_at"}:
        return

    # Capture user_id now (not the instance) for clean serialization to Celery
    user_id = instance.user_id

    from posthog.tasks.team_access_cache_tasks import warm_personal_api_key_teams_cache_task

    transaction.on_commit(lambda: warm_personal_api_key_teams_cache_task.delay(user_id))


@receiver(post_delete, sender=PersonalAPIKey)
def personal_api_key_deleted(sender, instance: "PersonalAPIKey", **kwargs):
    """
    Handle PersonalAPIKey delete for team access cache invalidation.
    """
    # Capture data now (not the instance) for clean serialization to Celery
    user_id = instance.user_id
    scoped_team_ids = list(instance.scoped_teams) if instance.scoped_teams else None

    from posthog.tasks.team_access_cache_tasks import warm_personal_api_key_deleted_cache_task

    transaction.on_commit(lambda: warm_personal_api_key_deleted_cache_task.delay(user_id, scoped_team_ids))


# --- User signal handlers ---


@receiver(post_save, sender=User)
def user_saved(sender, instance: "User", created, **kwargs):
    """
    Handle User save for team access cache updates when is_active changes.

    When a user's is_active status changes, their Personal API Keys need to be
    added or removed from team authentication caches.

    We track the original is_active value via User.from_db() to detect actual changes,
    avoiding unnecessary cache warming on unrelated user saves.

    Security consideration:
    - Deactivation (is_active: True -> False): Cache invalidation runs SYNCHRONOUSLY
      to immediately revoke access. This prevents a race condition where a deactivated
      user could continue using their API keys during Celery queue delays.
    - Activation (is_active: False -> True): Cache warming runs ASYNCHRONOUSLY via Celery
      since there's no security concern with a slight delay in granting access.
    """
    original_is_active = getattr(instance, "_original_is_active", instance.is_active)
    is_active_changed = created or instance.is_active != original_is_active

    if not is_active_changed:
        logger.debug(f"User {instance.id} saved but is_active unchanged, skipping cache update")
        return

    # Update the snapshot to prevent double-fires if the same instance is saved again
    instance._original_is_active = instance.is_active

    # Capture user_id now (not the instance) for clean serialization to Celery
    user_id = instance.id

    if instance.is_active:
        # User activated - async is fine, no security concern with delay
        from posthog.tasks.team_access_cache_tasks import warm_user_teams_cache_task

        transaction.on_commit(lambda: warm_user_teams_cache_task.delay(user_id))
    else:
        # User deactivated - sync to immediately revoke access (security-critical)
        from posthog.tasks.team_access_cache_tasks import warm_user_teams_cache_sync

        transaction.on_commit(lambda: warm_user_teams_cache_sync(user_id))


# --- OrganizationMembership signal handlers ---


@receiver(post_save, sender=OrganizationMembership)
def organization_membership_saved(sender, instance: "OrganizationMembership", created, **kwargs):
    """
    Handle OrganizationMembership creation for team access cache updates.

    When a user is added to an organization, their unscoped personal API keys
    should gain access to teams within that organization. This ensures
    that the authentication cache is updated to reflect the new access rights.

    Note: We intentionally only handle creation (created=True), not updates.
    Changes to membership level (e.g., MEMBER -> ADMIN) don't affect API key
    access - Personal API keys grant access based on organization membership
    existence, not role level.
    """
    if created:
        # Capture data now (not the instance) for clean serialization to Celery
        organization_id = str(instance.organization_id)
        user_id = instance.user_id

        from posthog.tasks.team_access_cache_tasks import warm_organization_teams_cache_task

        transaction.on_commit(
            lambda: warm_organization_teams_cache_task.delay(organization_id, user_id, "added to organization")
        )


@receiver(post_delete, sender=OrganizationMembership)
def organization_membership_deleted(sender, instance: "OrganizationMembership", **kwargs):
    """
    Handle OrganizationMembership deletion for team access cache invalidation.

    When a user is removed from an organization, their unscoped personal API keys
    should no longer have access to teams within that organization. This ensures
    that the authentication cache is updated to reflect the change in access rights.
    """
    # Capture data now (not the instance) for clean serialization to Celery
    organization_id = str(instance.organization_id)
    user_id = instance.user_id

    from posthog.tasks.team_access_cache_tasks import warm_organization_teams_cache_task

    transaction.on_commit(
        lambda: warm_organization_teams_cache_task.delay(organization_id, user_id, "removed from organization")
    )
