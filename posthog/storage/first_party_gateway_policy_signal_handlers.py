"""
Signal handlers that keep the first-party gateway policy cache in sync with
credential and user state.

The blob is keyed by the credential's hash, so a revoke, scope removal, or token
rotation that does not invalidate the cache leaves a stale entry usable for the
full TTL. Credential rows also don't change when a user switches their default
team or is deactivated, so a User.current_team_id or is_active change must
re-project that user's credentials — otherwise team_id/project_token go stale, or
a disabled user keeps gateway access until the TTL lapses (OAuth self-heals via
its short TTL, a personal key would not).

A pre_save fallback covers credentials loaded with the hash/scope fields deferred
(.only()/.defer()), where the post_init snapshot is skipped: without it a
deferred-load rotation would leave the old hash live for the full TTL.

Wired from PostHogConfig.ready() so the receivers register in every process that
can mutate a credential. All handlers no-op unless AI_GATEWAY_REDIS_URL is set,
and credential handlers do real work only for credentials that hold (or held) the
gateway scope — ordinary personal keys and the high volume of minted OAuth tokens
are skipped before any task is enqueued. Mutations must go through .save()/.delete();
bulk_update()/.update() bypass signals.
"""

from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_init, post_save, pre_delete, pre_save

import structlog

from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.user import User
from posthog.models.utils import SHA256_HASH_PREFIX
from posthog.storage.first_party_gateway_policy_cache import (
    FIRST_PARTY_REQUIRED_SCOPE,
    clear_first_party_policy,
    credential_has_gateway_scope,
)
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.tasks.first_party_gateway_policy import (
    reproject_user_first_party_policies_task,
    update_first_party_policy_cache_task,
)

logger = structlog.get_logger(__name__)

_NAMESPACE = "first_party_gateway_policy"

_LOADED_HASH_ATTR = "_fp_loaded_hash"
_LOADED_ELIGIBLE_ATTR = "_fp_loaded_eligible"
_LOADED_CURRENT_TEAM_ATTR = "_fp_loaded_current_team_id"
_LOADED_IS_ACTIVE_ATTR = "_fp_loaded_is_active"

_PAK_KIND = "personal_api_key"
_OAUTH_KIND = "oauth_access_token"


def _pak_hash(instance: PersonalAPIKey) -> str | None:
    return instance.secure_value


def _oauth_hash(instance: OAuthAccessToken) -> str | None:
    return f"{SHA256_HASH_PREFIX}{instance.token_checksum}" if instance.token_checksum else None


def _snapshot_pak(sender: type[PersonalAPIKey], instance: PersonalAPIKey, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    deferred = instance.get_deferred_fields()
    if "secure_value" in deferred or "scopes" in deferred:
        return
    instance.__dict__[_LOADED_HASH_ATTR] = _pak_hash(instance)
    instance.__dict__[_LOADED_ELIGIBLE_ATTR] = credential_has_gateway_scope(instance)


def _snapshot_oauth(sender: type[OAuthAccessToken], instance: OAuthAccessToken, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    deferred = instance.get_deferred_fields()
    if "token_checksum" in deferred or "scope" in deferred:
        return
    instance.__dict__[_LOADED_HASH_ATTR] = _oauth_hash(instance)
    instance.__dict__[_LOADED_ELIGIBLE_ATTR] = credential_has_gateway_scope(instance)


def _snapshot_user(sender: type[User], instance: User, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    deferred = instance.get_deferred_fields()
    if "current_team_id" not in deferred:
        instance.__dict__[_LOADED_CURRENT_TEAM_ATTR] = instance.current_team_id
    if "is_active" not in deferred:
        instance.__dict__[_LOADED_IS_ACTIVE_ATTR] = instance.is_active


def _capture_old_pak_if_deferred(sender: type[PersonalAPIKey], instance: PersonalAPIKey, **kwargs: Any) -> None:
    # Fallback for a PAK loaded with secure_value/scopes deferred (post_init
    # skipped the snapshot): re-read the old values before the UPDATE so a
    # deferred-load rotation still clears the old hash. No-op (no query) on the
    # common full-load path, where the snapshot is already present.
    if not settings.AI_GATEWAY_REDIS_URL or _LOADED_HASH_ATTR in instance.__dict__:
        return
    if not instance.pk or instance._state.adding:
        return
    row = PersonalAPIKey.objects.filter(pk=instance.pk).values("secure_value", "scopes").first()
    if row is None:
        return
    instance.__dict__[_LOADED_HASH_ATTR] = row["secure_value"]
    instance.__dict__[_LOADED_ELIGIBLE_ATTR] = FIRST_PARTY_REQUIRED_SCOPE in (row["scopes"] or [])


def _capture_old_oauth_if_deferred(sender: type[OAuthAccessToken], instance: OAuthAccessToken, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL or _LOADED_HASH_ATTR in instance.__dict__:
        return
    if not instance.pk or instance._state.adding:
        return
    row = OAuthAccessToken.objects.filter(pk=instance.pk).values("token_checksum", "scope").first()
    if row is None:
        return
    checksum = row["token_checksum"]
    instance.__dict__[_LOADED_HASH_ATTR] = f"{SHA256_HASH_PREFIX}{checksum}" if checksum else None
    instance.__dict__[_LOADED_ELIGIBLE_ATTR] = FIRST_PARTY_REQUIRED_SCOPE in (row["scope"] or "").split()


def _on_credential_save(
    kind: str, instance: PersonalAPIKey | OAuthAccessToken, new_hash: str | None, eligible_now: bool
) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return

    old_hash: str | None = instance.__dict__.get(_LOADED_HASH_ATTR)
    old_eligible: bool = instance.__dict__.get(_LOADED_ELIGIBLE_ATTR, False)
    instance.__dict__[_LOADED_HASH_ATTR] = new_hash
    instance.__dict__[_LOADED_ELIGIBLE_ATTR] = eligible_now

    # Overwhelmingly common: a credential that never had and still lacks the
    # gateway scope has nothing to project or clear. Skip before touching Celery
    # or Redis — OAuth tokens mint constantly and would otherwise flood the queue.
    if not eligible_now and not old_eligible:
        return

    def enqueue() -> None:
        try:
            # A rotated/changed hash leaves the old key live for the full TTL —
            # clear it synchronously so the stale secret stops authenticating now.
            if old_hash and old_hash != new_hash:
                clear_first_party_policy(old_hash)
            if eligible_now:
                update_first_party_policy_cache_task.delay(kind, str(instance.pk))
            elif new_hash:
                # Scope was removed: clear promptly rather than waiting for a task.
                clear_first_party_policy(new_hash)
        except Exception as e:
            HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(namespace=_NAMESPACE, operation="enqueue", result="failure").inc()
            logger.exception("Failed to enqueue first-party policy cache update", kind=kind, error=str(e))

    transaction.on_commit(enqueue)


def _update_pak_on_save(sender: type[PersonalAPIKey], instance: PersonalAPIKey, created: bool, **kwargs: Any) -> None:
    _on_credential_save(_PAK_KIND, instance, _pak_hash(instance), credential_has_gateway_scope(instance))


def _update_oauth_on_save(
    sender: type[OAuthAccessToken], instance: OAuthAccessToken, created: bool, **kwargs: Any
) -> None:
    _on_credential_save(_OAUTH_KIND, instance, _oauth_hash(instance), credential_has_gateway_scope(instance))


def _clear_pak_on_delete(sender: type[PersonalAPIKey], instance: PersonalAPIKey, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL or not credential_has_gateway_scope(instance):
        return
    cache_hash = _pak_hash(instance)
    if cache_hash:
        clear_first_party_policy(cache_hash)


def _clear_oauth_on_delete(sender: type[OAuthAccessToken], instance: OAuthAccessToken, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL or not credential_has_gateway_scope(instance):
        return
    cache_hash = _oauth_hash(instance)
    if cache_hash:
        clear_first_party_policy(cache_hash)


def _reproject_user_on_save(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    # A credential row doesn't change when the user switches default team or is
    # deactivated, so reproject on either. A team change re-points
    # team_id/project_token; deactivation makes _policy_for_credential return
    # Missing, so the same task clears the blobs (and reactivation re-grants).
    if not settings.AI_GATEWAY_REDIS_URL or created:
        return
    old_team_id = instance.__dict__.get(_LOADED_CURRENT_TEAM_ATTR)
    old_is_active = instance.__dict__.get(_LOADED_IS_ACTIVE_ATTR)
    instance.__dict__[_LOADED_CURRENT_TEAM_ATTR] = instance.current_team_id
    instance.__dict__[_LOADED_IS_ACTIVE_ATTR] = instance.is_active

    team_changed = old_team_id is not None and old_team_id != instance.current_team_id
    active_changed = old_is_active is not None and old_is_active != instance.is_active
    if not (team_changed or active_changed):
        return

    user_id = instance.pk
    transaction.on_commit(lambda: reproject_user_first_party_policies_task.delay(user_id))


def connect_signal_handlers() -> None:
    post_init.connect(_snapshot_pak, sender=PersonalAPIKey)
    pre_save.connect(_capture_old_pak_if_deferred, sender=PersonalAPIKey)
    post_save.connect(_update_pak_on_save, sender=PersonalAPIKey)
    pre_delete.connect(_clear_pak_on_delete, sender=PersonalAPIKey)

    post_init.connect(_snapshot_oauth, sender=OAuthAccessToken)
    pre_save.connect(_capture_old_oauth_if_deferred, sender=OAuthAccessToken)
    post_save.connect(_update_oauth_on_save, sender=OAuthAccessToken)
    pre_delete.connect(_clear_oauth_on_delete, sender=OAuthAccessToken)

    post_init.connect(_snapshot_user, sender=User)
    post_save.connect(_reproject_user_on_save, sender=User)
