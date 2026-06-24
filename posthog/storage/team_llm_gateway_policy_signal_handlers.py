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

logger = structlog.get_logger(__name__)

# Snapshots of the values a Team was loaded with, so post_save can detect a
# rotation (api_token) or an admission flip (llm_gateway_enabled_at,
# llm_gateway_revoked_at) without an extra DB read.
_LOADED_API_TOKEN_ATTR = "_llm_gateway_loaded_api_token"
_LOADED_ENABLED_AT_ATTR = "_llm_gateway_loaded_enabled_at"
_LOADED_REVOKED_AT_ATTR = "_llm_gateway_loaded_revoked_at"
_TRACKED_FIELDS = ("api_token", "llm_gateway_enabled_at", "llm_gateway_revoked_at")
_NO_SNAPSHOT = object()


def _snapshot_loaded_state(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    """
    Record the instance's current api_token, llm_gateway_enabled_at, and
    llm_gateway_revoked_at on post_init so the post_save handler can spot a
    rotation or admission flip without a DB read. Skip a field when it is
    deferred (e.g. a .only() fetch) so we never trigger a lazy load.
    """
    deferred = instance.get_deferred_fields()
    if "api_token" not in deferred:
        instance.__dict__[_LOADED_API_TOKEN_ATTR] = instance.api_token
    if "llm_gateway_enabled_at" not in deferred:
        instance.__dict__[_LOADED_ENABLED_AT_ATTR] = instance.llm_gateway_enabled_at
    if "llm_gateway_revoked_at" not in deferred:
        instance.__dict__[_LOADED_REVOKED_AT_ATTR] = instance.llm_gateway_revoked_at


def _capture_old_state_if_deferred(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    """
    Fallback for instances loaded with any tracked field deferred: capture
    the old values from the DB before the UPDATE runs. No-op (zero query) for
    the common full-load path, where post_init already snapshotted. Without
    this, a deferred-load rotation or admission flip would leave the previous
    cache entry live for the full 7-day TTL.
    """
    if not instance.pk or instance._state.adding:
        return
    need_api = _LOADED_API_TOKEN_ATTR not in instance.__dict__
    need_enabled = _LOADED_ENABLED_AT_ATTR not in instance.__dict__
    need_revoked = _LOADED_REVOKED_AT_ATTR not in instance.__dict__
    if not (need_api or need_enabled or need_revoked):
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not (set(_TRACKED_FIELDS) & set(update_fields)):
        return
    fields: list[str] = []
    if need_api:
        fields.append("api_token")
    if need_enabled:
        fields.append("llm_gateway_enabled_at")
    if need_revoked:
        fields.append("llm_gateway_revoked_at")
    try:
        row = Team.objects.filter(pk=instance.pk).values(*fields).first()
    except OperationalError:
        # Mirror the loader: log so an operational hiccup mid-rotation is
        # visible instead of silently leaking the old cache for the full TTL.
        logger.exception(
            "Database error capturing old Team state for llm-gateway cache invalidation",
            team_id=instance.pk,
        )
        return
    if row is None:
        return
    if need_api and row.get("api_token") is not None:
        instance.__dict__[_LOADED_API_TOKEN_ATTR] = row["api_token"]
    if need_enabled:
        instance.__dict__[_LOADED_ENABLED_AT_ATTR] = row.get("llm_gateway_enabled_at")
    if need_revoked:
        instance.__dict__[_LOADED_REVOKED_AT_ATTR] = row.get("llm_gateway_revoked_at")


def _value_changed(instance: Team, snapshot_attr: str, field_name: str) -> bool:
    """Sentinel-based change check: True only when both old and new are present and differ.
    Reads via __dict__ to skip lazy-load on deferred fields."""
    old = instance.__dict__.get(snapshot_attr, _NO_SNAPSHOT)
    new = instance.__dict__.get(field_name, _NO_SNAPSHOT)
    return old is not _NO_SNAPSHOT and new is not _NO_SNAPSHOT and old != new


def _update_cache_on_save(sender: type[Team], instance: Team, created: bool, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return

    old_api_token: str | None = instance.__dict__.get(_LOADED_API_TOKEN_ATTR)
    rotated = bool(old_api_token and old_api_token != instance.api_token)

    enabled_changed = _value_changed(instance, _LOADED_ENABLED_AT_ATTR, "llm_gateway_enabled_at")
    revoked_changed = _value_changed(instance, _LOADED_REVOKED_AT_ATTR, "llm_gateway_revoked_at")
    admission_changed = enabled_changed or revoked_changed

    # Re-snapshot so chained changes compare against the just-saved values.
    instance.__dict__[_LOADED_API_TOKEN_ATTR] = instance.api_token
    new_enabled_at = instance.__dict__.get("llm_gateway_enabled_at", _NO_SNAPSHOT)
    if new_enabled_at is not _NO_SNAPSHOT:
        instance.__dict__[_LOADED_ENABLED_AT_ATTR] = new_enabled_at
    new_revoked_at = instance.__dict__.get("llm_gateway_revoked_at", _NO_SNAPSHOT)
    if new_revoked_at is not _NO_SNAPSHOT:
        instance.__dict__[_LOADED_REVOKED_AT_ATTR] = new_revoked_at

    def enqueue_task() -> None:
        # posthog.tasks.__init__ eagerly imports every task module (celery autoimport);
        # this signal module is wired at django.setup(), so import the task lazily.
        from posthog.tasks.team_llm_gateway_policy import update_team_llm_gateway_policy_cache_task  # noqa: PLC0415

        try:
            update_team_llm_gateway_policy_cache_task.delay(instance.id)
            kinds = ["redis"] if settings.TEST else None
            if rotated and old_api_token is not None:
                # Same on-commit flow as the refresh so the old cache entry
                # disappears the moment the rotated token becomes live.
                clear_team_llm_gateway_policy_cache(old_api_token, kinds=kinds)
            if admission_changed:
                # Invalidate the current token's entry synchronously so the next
                # gateway request reads the fresh admission state from the DB.
                # The async refresh task can lag, leaving the stale policy
                # usable for the full cache TTL.
                clear_team_llm_gateway_policy_cache(instance, kinds=kinds)
        except Exception as e:
            HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
                namespace="team_metadata",
                cache_name="llm_gateway_policy",
                operation="enqueue",
                result="failure",
            ).inc()
            logger.exception(
                "Failed to enqueue llm-gateway policy cache update",
                team_id=instance.id,
                error=str(e),
            )

    transaction.on_commit(enqueue_task)


def _clear_cache_on_delete(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return

    kinds = ["redis"] if settings.TEST else None
    clear_team_llm_gateway_policy_cache(instance, kinds=kinds)


def connect_signal_handlers() -> None:
    post_init.connect(_snapshot_loaded_state, sender=Team)
    pre_save.connect(_capture_old_state_if_deferred, sender=Team)
    post_save.connect(_update_cache_on_save, sender=Team)
    pre_delete.connect(_clear_cache_on_delete, sender=Team)
