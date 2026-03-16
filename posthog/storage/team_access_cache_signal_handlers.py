"""
Signal handler functions for per-token auth cache invalidation.

Handles Team model changes (secret token rotation, deletion) and provides
capture_old_pak_secure_value for PersonalAPIKey pre-save capture.

PersonalAPIKey, User, and OrganizationMembership post-save invalidation is
handled by Celery tasks dispatched from @receiver handlers in
posthog/models/remote_config.py.
"""

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team.team import Team
from posthog.storage.team_access_cache import token_auth_cache

logger = structlog.get_logger(__name__)

_SECRET_TOKEN_FIELDS = frozenset({"secret_api_token", "secret_api_token_backup"})
_PAK_AUTH_FIELDS = frozenset({"secure_value"})


def capture_old_pak_secure_value(instance: PersonalAPIKey, **kwargs):
    """
    Capture the old secure_value before a PersonalAPIKey save.

    Stored on the instance so post_save can invalidate the old cache entry
    when secure_value changes in-place (key rolling), preventing the old
    token hash from remaining valid in Redis for up to the 30-day TTL.
    """
    if not instance.pk:
        return

    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not _PAK_AUTH_FIELDS.intersection(update_fields):
        return

    try:
        old_pak = PersonalAPIKey.objects.only("secure_value").get(pk=instance.pk)
        instance._old_secure_value = old_pak.secure_value  # type: ignore[attr-defined]
    except PersonalAPIKey.DoesNotExist:
        pass


def capture_old_secret_tokens(instance: Team, **kwargs):
    """
    Capture old secret_api_token and secret_api_token_backup before save.

    The pre_save handler stores old values so the post_save handler can
    invalidate the correct cache entries when tokens change or rotate.
    """
    if not instance.pk:
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


def update_team_authentication_cache(instance: Team, created: bool, **kwargs):
    """
    Invalidate specific token cache entries when Team auth fields change.

    On secret token rotation: the old secret_api_token becomes the new backup,
    and the old backup is discarded. We invalidate the discarded backup's hash.

    On direct change: invalidate the old token's hash.
    """
    try:
        if created or not instance.api_token:
            return

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            if not _SECRET_TOKEN_FIELDS.intersection(update_fields):
                return

        # Handle secret token rotation: old backup is discarded
        old_backup = getattr(instance, "_old_secret_api_token_backup", None)
        old_secret = getattr(instance, "_old_secret_api_token", None)

        if old_backup and old_backup != instance.secret_api_token_backup:
            # The old backup was discarded during rotation — invalidate its cache entry
            old_backup_hash = hash_key_value(old_backup, mode="sha256")
            token_auth_cache.invalidate_token(old_backup_hash)
            logger.info("Invalidated discarded backup token for team", team_id=instance.pk)

        if old_secret and old_secret != instance.secret_api_token:
            # During rotation the old primary becomes the new backup and stays valid,
            # so only invalidate it when it is not the current backup.
            if old_secret != instance.secret_api_token_backup:
                old_secret_hash = hash_key_value(old_secret, mode="sha256")
                token_auth_cache.invalidate_token(old_secret_hash)
                logger.info("Invalidated old secret token for team", team_id=instance.pk)

    except Exception as e:
        capture_exception(e)
        logger.exception("Error updating auth cache on team save", team_id=instance.pk)


def update_team_authentication_cache_on_delete(instance: Team, **kwargs):
    """Invalidate cached secret tokens when a team is deleted.

    Teams have at most two secret tokens (secret_api_token and its backup),
    so we hash and invalidate each directly.
    """
    try:
        if not instance.pk:
            return

        for token in (instance.secret_api_token, instance.secret_api_token_backup):
            if token:
                token_hash = hash_key_value(token, mode="sha256")
                token_auth_cache.invalidate_token(token_hash)

        logger.info("Invalidated cached tokens for deleted team", team_id=instance.pk)
    except Exception as e:
        capture_exception(e)
        logger.exception("Error invalidating cache on team delete", team_id=instance.pk)
