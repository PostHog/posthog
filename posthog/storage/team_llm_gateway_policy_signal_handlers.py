"""
Signal handlers that keep the llm-gateway policy cache in sync with Team state.

Wired from PostHogConfig.ready() via connect_signal_handlers() so the receivers
register in every Django process that can mutate a Team (web, asgi, workers),
not only the ones that happen to import the Celery task module. The llm-gateway
policy blob is keyed by api_token, so a revocation or token rotation that does
not invalidate the cache leaves a stale entry usable for the full cache TTL.

Cache mutations must go through Team.save()/.delete(); Team.objects.update() and
bulk_update() bypass Django signals and would leak the old cache entry.
"""

from typing import Any

from django.conf import settings
from django.db import OperationalError, transaction
from django.db.models.signals import post_init, post_save, pre_delete, pre_save

import structlog

from posthog.models.team import Team
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.storage.team_llm_gateway_policy_cache import clear_team_llm_gateway_policy_cache
from posthog.tasks.team_llm_gateway_policy import update_team_llm_gateway_policy_cache_task

logger = structlog.get_logger(__name__)

# Snapshots of the values a Team was loaded with, so post_save can detect a
# rotation (api_token) or a revocation flip (llm_gateway_revoked_at) without an
# extra DB read.
_LOADED_API_TOKEN_ATTR = "_llm_gateway_loaded_api_token"
_LOADED_REVOKED_AT_ATTR = "_llm_gateway_loaded_revoked_at"
_NO_SNAPSHOT = object()


def _snapshot_loaded_state(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    """
    Record the instance's current api_token and llm_gateway_revoked_at on
    post_init so the post_save handler can spot a rotation or revocation flip
    without a DB read. Skip a field when it is deferred (e.g. a .only() fetch)
    so we never trigger a lazy load.
    """
    deferred = instance.get_deferred_fields()
    if "api_token" not in deferred:
        instance.__dict__[_LOADED_API_TOKEN_ATTR] = instance.api_token
    if "llm_gateway_revoked_at" not in deferred:
        instance.__dict__[_LOADED_REVOKED_AT_ATTR] = instance.llm_gateway_revoked_at


def _capture_old_state_if_deferred(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    """
    Fallback for instances loaded with api_token or llm_gateway_revoked_at
    deferred: capture the old values from the DB before the UPDATE runs.
    No-op (zero query) for the common full-load path, where post_init already
    snapshotted. Without this, a deferred-load rotation or revocation would
    leave the previous cache entry live for the full 7-day TTL.
    """
    if not instance.pk or instance._state.adding:
        return
    need_api = _LOADED_API_TOKEN_ATTR not in instance.__dict__
    need_rev = _LOADED_REVOKED_AT_ATTR not in instance.__dict__
    if not need_api and not need_rev:
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not ({"api_token", "llm_gateway_revoked_at"} & set(update_fields)):
        return
    fields: list[str] = []
    if need_api:
        fields.append("api_token")
    if need_rev:
        fields.append("llm_gateway_revoked_at")
    try:
        row = Team.objects.filter(pk=instance.pk).values(*fields).first()
    except OperationalError:
        return
    if row is None:
        return
    if need_api and row.get("api_token") is not None:
        instance.__dict__[_LOADED_API_TOKEN_ATTR] = row["api_token"]
    if need_rev:
        instance.__dict__[_LOADED_REVOKED_AT_ATTR] = row.get("llm_gateway_revoked_at")


def _update_cache_on_save(sender: type[Team], instance: Team, created: bool, **kwargs: Any) -> None:
    if not settings.FLAGS_REDIS_URL:
        return

    old_api_token: str | None = instance.__dict__.get(_LOADED_API_TOKEN_ATTR)
    rotated = bool(old_api_token and old_api_token != instance.api_token)

    # Use a sentinel so "no snapshot" (deferred + no fallback) is distinguishable
    # from "snapshot of None" (loaded as null). We only act on an observed change.
    old_revoked_at = instance.__dict__.get(_LOADED_REVOKED_AT_ATTR, _NO_SNAPSHOT)
    new_revoked_at = instance.llm_gateway_revoked_at
    revoked_changed = old_revoked_at is not _NO_SNAPSHOT and old_revoked_at != new_revoked_at

    # Re-snapshot so chained changes compare against the just-saved values.
    instance.__dict__[_LOADED_API_TOKEN_ATTR] = instance.api_token
    instance.__dict__[_LOADED_REVOKED_AT_ATTR] = new_revoked_at

    def enqueue_task() -> None:
        try:
            update_team_llm_gateway_policy_cache_task.delay(instance.id)
            kinds = ["redis"] if settings.TEST else None
            if rotated and old_api_token is not None:
                # Same on-commit flow as the refresh so the old cache entry
                # disappears the moment the rotated token becomes live.
                clear_team_llm_gateway_policy_cache(old_api_token, kinds=kinds)
            if revoked_changed:
                # Invalidate the current token's entry synchronously so the next
                # gateway request reads the fresh revocation state from the DB.
                # The async refresh task can lag, leaving the stale active
                # policy usable for the full cache TTL.
                clear_team_llm_gateway_policy_cache(instance, kinds=kinds)
        except Exception as e:
            HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
                namespace="team_llm_gateway_policy", operation="enqueue", result="failure"
            ).inc()
            logger.exception(
                "Failed to enqueue llm-gateway policy cache update",
                team_id=instance.id,
                error=str(e),
            )

    transaction.on_commit(enqueue_task)


def _clear_cache_on_delete(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    if not settings.FLAGS_REDIS_URL:
        return

    kinds = ["redis"] if settings.TEST else None
    clear_team_llm_gateway_policy_cache(instance, kinds=kinds)


def connect_signal_handlers() -> None:
    post_init.connect(_snapshot_loaded_state, sender=Team)
    pre_save.connect(_capture_old_state_if_deferred, sender=Team)
    post_save.connect(_update_cache_on_save, sender=Team)
    pre_delete.connect(_clear_cache_on_delete, sender=Team)
