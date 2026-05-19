"""
Signal handlers for per-token auth cache invalidation.

This module registers @receiver signal handlers that automatically invalidate
per-token auth cache entries when Team, PersonalAPIKey, ProjectSecretAPIKey,
User, and OrganizationMembership models change.

Cache invalidation implementations live in posthog/tasks/team_access_cache_tasks.py.
"""

from collections.abc import Callable
from typing import Any

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch.dispatcher import receiver

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User

logger = structlog.get_logger(__name__)

_SECRET_TOKEN_FIELDS = frozenset({"secret_api_token", "secret_api_token_backup"})
_KEY_AUTH_FIELDS = frozenset({"secure_value"})


# --- Generic secure_value capture ---


def _capture_old_secure_value(
    model_class: type[PersonalAPIKey] | type[ProjectSecretAPIKey],
    instance: Any,
    **kwargs,
) -> None:
    """
    Capture the old secure_value before an API key save.

    Stored on the instance so post_save can invalidate the old cache entry
    when secure_value changes in-place (key rolling), preventing the old
    token hash from remaining valid in Redis for up to the cache TTL.

    Works for both PersonalAPIKey and ProjectSecretAPIKey.
    Skips the DB query if the model's save() override already stashed the value.
    """
    if not instance.pk or instance._state.adding:
        return

    # If the model's save() already captured the old value, skip the DB query.
    # Use __dict__ instead of hasattr because hasattr auto-creates attributes on MagicMock.
    if "_old_secure_value" in instance.__dict__:
        return

    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not _KEY_AUTH_FIELDS.intersection(update_fields):
        return

    try:
        old = model_class.objects.only("secure_value").get(pk=instance.pk)
        instance._old_secure_value = old.secure_value
    except model_class.DoesNotExist:
        pass


def capture_old_pak_secure_value(instance: PersonalAPIKey, **kwargs):
    """Capture old secure_value before PersonalAPIKey save for cache invalidation."""
    _capture_old_secure_value(PersonalAPIKey, instance, **kwargs)


def capture_old_psak_secure_value(instance: ProjectSecretAPIKey, **kwargs):
    """Capture old secure_value before ProjectSecretAPIKey save for cache invalidation."""
    _capture_old_secure_value(ProjectSecretAPIKey, instance, **kwargs)


# --- Team signal handlers ---


def capture_old_secret_tokens(instance: Team, **kwargs):
    """
    Capture old secret_api_token and secret_api_token_backup before save.

    The pre_save handler stores old values so the post_save handler can
    invalidate the correct cache entries when tokens change or rotate.
    """
    if not instance.pk or instance._state.adding:
        return

    # Skip the DB read when update_fields is specified and doesn't include auth fields
    update_fields = kwargs.get("update_fields")
    if update_fields is not None:
        if not _SECRET_TOKEN_FIELDS.intersection(update_fields):
            return

    try:
        old_team = Team.objects.only("secret_api_token", "secret_api_token_backup").get(pk=instance.pk)
        instance._old_secret_api_token = old_team.secret_api_token  # type: ignore[attr-defined]
        instance._old_secret_api_token_backup = old_team.secret_api_token_backup  # type: ignore[attr-defined]
    except Team.DoesNotExist:
        pass


@receiver(pre_save, sender=Team)
def team_pre_save_auth_cache(sender, instance: "Team", **kwargs):
    """Capture old secret token values before save for cache cleanup."""
    capture_old_secret_tokens(instance, **kwargs)


@receiver(post_save, sender=Team)
def team_saved_auth_cache(sender, instance: "Team", created, **kwargs):
    """Update team authentication cache on team save."""
    transaction.on_commit(lambda: _update_team_authentication_cache(instance, created))


@receiver(post_delete, sender=Team)
def team_deleted_auth_cache(sender, instance: "Team", **kwargs):
    """Handle team deletion for access cache."""
    transaction.on_commit(lambda: _update_team_authentication_cache_on_delete(instance))


def _update_team_authentication_cache(instance: Team, created: bool):
    """
    Invalidate specific token cache entries when Team auth fields change.

    Called from a transaction.on_commit callback, so the DB transaction has
    already committed and invalidation runs synchronously for immediate effect.

    On secret token rotation: the old secret_api_token becomes the new backup,
    and the old backup is discarded. We invalidate the discarded backup's hash.

    On direct change: invalidate the old token's hash.

    Note: update_fields filtering is handled by capture_old_secret_tokens (pre_save).
    If no auth fields changed, _old_secret_* attrs won't be set, and the getattr()
    calls below return None, skipping invalidation.
    """
    try:
        # Guard on api_token (the public phc_ token) as a proxy for "fully initialized team".
        # A team without a public token has not completed setup, so its secret tokens
        # are not in use and don't need cache invalidation.
        if created or not instance.api_token:
            return

        from posthog.tasks.team_access_cache_tasks import invalidate_token_sync

        # Handle secret token rotation: old backup is discarded
        old_backup = getattr(instance, "_old_secret_api_token_backup", None)
        old_secret = getattr(instance, "_old_secret_api_token", None)

        if old_backup and old_backup != instance.secret_api_token_backup:
            # The old backup was discarded during rotation — invalidate its cache entry
            old_backup_hash = hash_key_value(old_backup, mode="sha256")
            invalidate_token_sync(old_backup_hash)
            logger.info("Invalidated discarded backup token", team_id=instance.pk)

        if old_secret and old_secret != instance.secret_api_token:
            # During rotation the old primary becomes the new backup and stays valid,
            # so only invalidate it when it is not the current backup.
            if old_secret != instance.secret_api_token_backup:
                old_secret_hash = hash_key_value(old_secret, mode="sha256")
                invalidate_token_sync(old_secret_hash)
                logger.info("Invalidated old secret token", team_id=instance.pk)

    except Exception as e:
        capture_exception(e)
        logger.exception("Error updating auth cache on team save", team_id=instance.pk)


def _update_team_authentication_cache_on_delete(instance: Team):
    """Invalidate cached secret tokens when a team is deleted.

    Called from a transaction.on_commit callback, so the DB transaction has
    already committed and invalidation runs synchronously for immediate effect.
    """
    try:
        if not instance.pk:
            return

        from posthog.tasks.team_access_cache_tasks import invalidate_token_sync

        for token in (instance.secret_api_token, instance.secret_api_token_backup):
            if token:
                token_hash = hash_key_value(token, mode="sha256")
                invalidate_token_sync(token_hash)

        logger.info("Invalidated deleted team tokens", team_id=instance.pk)
    except Exception as e:
        capture_exception(e)
        logger.exception("Error invalidating cache on team delete", team_id=instance.pk)


# --- PersonalAPIKey signal handlers ---


def _defer_token_invalidation(secure_value: str) -> None:
    """Invalidate an auth token cache entry synchronously after commit."""
    from posthog.tasks.team_access_cache_tasks import invalidate_token_sync

    transaction.on_commit(lambda: invalidate_token_sync(secure_value))


# PAK fields whose changes affect cached TokenAuthData and require cache invalidation.
# secure_value: the token hash itself (cache key)
# scopes, scoped_teams, scoped_organizations: cached in TokenAuthData::Personal
_PAK_CACHE_RELEVANT_FIELDS = frozenset({"secure_value", "scopes", "scoped_teams", "scoped_organizations"})


def _handle_api_key_saved(
    instance: PersonalAPIKey | ProjectSecretAPIKey,
    created: bool,
    relevant_fields: frozenset[str],
    invalidate_fn: Callable[[str], None],
    **kwargs,
) -> None:
    """Handle post_save for PAK/PSAK auth cache invalidation.

    Skips non-auth field updates (e.g. last_used_at, label) and newly created
    keys (not cached yet). When secure_value changes in-place (key rolling),
    invalidates the old hash so it doesn't remain cached for up to the cache TTL.
    """
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not relevant_fields.intersection(update_fields):
        return

    if created:
        return

    secure_value = instance.secure_value
    old_secure_value = getattr(instance, "_old_secure_value", None)

    if secure_value:
        invalidate_fn(secure_value)

    if old_secure_value and old_secure_value != secure_value:
        invalidate_fn(old_secure_value)


@receiver(pre_save, sender=PersonalAPIKey)
def personal_api_key_pre_save(sender, instance: "PersonalAPIKey", **kwargs):
    """Capture old secure_value before save so post_save can invalidate the old cache entry."""
    capture_old_pak_secure_value(instance, **kwargs)


@receiver(post_save, sender=PersonalAPIKey)
def personal_api_key_saved(sender, instance: "PersonalAPIKey", created, **kwargs):
    _handle_api_key_saved(instance, created, _PAK_CACHE_RELEVANT_FIELDS, _defer_token_invalidation, **kwargs)


@receiver(post_delete, sender=PersonalAPIKey)
def personal_api_key_deleted(sender, instance: "PersonalAPIKey", **kwargs):
    if instance.secure_value:
        _defer_token_invalidation(instance.secure_value)


# --- ProjectSecretAPIKey signal handlers ---


# PSAK fields whose changes affect cached TokenAuthData and require cache invalidation.
_PSAK_CACHE_RELEVANT_FIELDS = frozenset({"secure_value", "scopes"})


@receiver(pre_save, sender=ProjectSecretAPIKey)
def project_secret_api_key_pre_save(sender, instance: "ProjectSecretAPIKey", **kwargs):
    """Capture old secure_value before save so post_save can invalidate the old cache entry."""
    capture_old_psak_secure_value(instance, **kwargs)


@receiver(post_save, sender=ProjectSecretAPIKey)
def project_secret_api_key_saved(sender, instance: "ProjectSecretAPIKey", created, **kwargs):
    _handle_api_key_saved(instance, created, _PSAK_CACHE_RELEVANT_FIELDS, _defer_token_invalidation, **kwargs)


@receiver(post_delete, sender=ProjectSecretAPIKey)
def project_secret_api_key_deleted(sender, instance: "ProjectSecretAPIKey", **kwargs):
    if instance.secure_value:
        _defer_token_invalidation(instance.secure_value)


# --- User signal handlers ---


@receiver(post_save, sender=User)
def user_saved(sender, instance: "User", created, **kwargs):
    """
    Handle User save for per-token auth cache invalidation when is_active changes.

    We track the original is_active value via User.from_db() to detect actual changes,
    avoiding unnecessary invalidation on unrelated user saves.

    Invalidation runs synchronously for immediate effect. If the sync attempt fails,
    an async Celery retry is scheduled as a safety net.
    """
    # Brand-new users have no cached tokens; nothing to invalidate.
    if created:
        return

    original_is_active = getattr(instance, "_original_is_active", instance.is_active)
    if instance.is_active == original_is_active:
        return

    # Update the snapshot to prevent double-fires if the same instance is saved again
    instance._original_is_active = instance.is_active

    # Capture user_id now (not the instance) for clean serialization to Celery
    user_id = instance.id

    from posthog.tasks.team_access_cache_tasks import invalidate_user_tokens_sync

    transaction.on_commit(lambda: invalidate_user_tokens_sync(user_id))


# --- OrganizationMembership signal handlers ---


@receiver(post_save, sender=OrganizationMembership)
def organization_membership_saved(sender, instance: "OrganizationMembership", created, **kwargs):
    """
    Handle OrganizationMembership creation for per-token auth cache invalidation.

    When a user is added to an organization, invalidate their cached tokens so
    the next request re-fetches from DB with updated org membership. Only handles
    creation — role changes (MEMBER -> ADMIN) don't affect API key access.
    """
    if created:
        user_id = instance.user_id
        if not user_id:
            return

        from posthog.tasks.team_access_cache_tasks import invalidate_user_tokens_sync

        transaction.on_commit(lambda: invalidate_user_tokens_sync(user_id))


@receiver(post_delete, sender=OrganizationMembership)
def organization_membership_deleted(sender, instance: "OrganizationMembership", **kwargs):
    """
    Handle OrganizationMembership deletion for per-token auth cache invalidation.

    When a user is removed from an organization, invalidate their cached tokens
    so org_ids are re-fetched from DB on next auth attempt.

    Uses synchronous invalidation (like user deactivation) because this is an
    access-revocation event: the user should lose access to teams in this org
    immediately, not after Celery queue delay.
    """
    user_id = instance.user_id
    if not user_id:
        return

    from posthog.tasks.team_access_cache_tasks import invalidate_user_tokens_sync

    transaction.on_commit(lambda: invalidate_user_tokens_sync(user_id))


# --- Team pre_delete: clear PSAK auth cache entries ---


@receiver(pre_delete, sender=Team)
def clear_project_secret_api_key_cache_on_delete(sender: type["Team"], instance: "Team", **kwargs) -> None:
    """Clear auth token cache entries for project secret API keys when a Team is deleted.

    Captures PSAK secure_values in pre_delete (before cascade deletes them),
    then defers the Redis invalidation to transaction.on_commit so we don't
    block the delete transaction on a Redis round-trip or invalidate on rollback.
    """
    from posthog.storage.team_access_cache import token_auth_cache

    if not token_auth_cache.is_configured:
        return

    secure_values: list[str] = list(
        instance.project_secret_api_keys.filter(secure_value__isnull=False).values_list("secure_value", flat=True)  # type: ignore[arg-type]  # filter guarantees non-null
    )

    if not secure_values:
        return

    def _invalidate_tokens_on_commit() -> None:
        try:
            token_auth_cache.invalidate_tokens(secure_values)
        except Exception as e:
            capture_exception(e)
            logger.exception("Error invalidating PSAK cache on team delete", team_id=instance.pk)

    transaction.on_commit(_invalidate_tokens_on_commit)
