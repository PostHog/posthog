"""
Signal handlers that keep the first-party gateway policy cache in sync with
credential and user state.

The blob is keyed by the credential's hash, so a revoke, scope removal, or token
rotation that does not invalidate the cache leaves a stale entry usable for the
full TTL. Credential rows also don't change when a user switches their default
team, so a User.current_team_id change must re-project that user's credentials —
otherwise team_id/project_token go stale (OAuth self-heals via its short TTL, a
personal key would not).

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
from django.db.models.signals import post_init, post_save, pre_delete

import structlog

from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.user import User
from posthog.models.utils import SHA256_HASH_PREFIX
from posthog.storage.first_party_gateway_policy_cache import clear_first_party_policy, credential_has_gateway_scope
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
    if not settings.AI_GATEWAY_REDIS_URL or "current_team_id" in instance.get_deferred_fields():
        return
    instance.__dict__[_LOADED_CURRENT_TEAM_ATTR] = instance.current_team_id


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


def _reproject_user_on_team_change(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL or created:
        return
    old_team_id = instance.__dict__.get(_LOADED_CURRENT_TEAM_ATTR)
    instance.__dict__[_LOADED_CURRENT_TEAM_ATTR] = instance.current_team_id
    if old_team_id is None or old_team_id == instance.current_team_id:
        return

    user_id = instance.pk
    transaction.on_commit(lambda: reproject_user_first_party_policies_task.delay(user_id))


def connect_signal_handlers() -> None:
    post_init.connect(_snapshot_pak, sender=PersonalAPIKey)
    post_save.connect(_update_pak_on_save, sender=PersonalAPIKey)
    pre_delete.connect(_clear_pak_on_delete, sender=PersonalAPIKey)

    post_init.connect(_snapshot_oauth, sender=OAuthAccessToken)
    post_save.connect(_update_oauth_on_save, sender=OAuthAccessToken)
    pre_delete.connect(_clear_oauth_on_delete, sender=OAuthAccessToken)

    post_init.connect(_snapshot_user, sender=User)
    post_save.connect(_reproject_user_on_team_change, sender=User)
