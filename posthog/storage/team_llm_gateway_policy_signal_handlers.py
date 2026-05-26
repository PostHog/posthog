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
from django.db import transaction
from django.db.models.signals import post_save, pre_delete, pre_save

import structlog

from posthog.models.team import Team
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.storage.team_llm_gateway_policy_cache import clear_team_llm_gateway_policy_cache
from posthog.tasks.team_llm_gateway_policy import update_team_llm_gateway_policy_cache_task

logger = structlog.get_logger(__name__)


def _capture_old_api_token(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    """
    Stash the previous api_token on the instance so the post_save handler can
    invalidate the cache entry keyed by the OLD token after a rotation. The
    post_save handler pops it once read, so a kept-alive instance saved twice
    (A->B->C) re-snapshots on each save instead of clearing A twice.
    """
    if not instance.pk or instance._state.adding:
        return

    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "api_token" not in update_fields:
        return

    try:
        old_team = Team.objects.only("api_token").get(pk=instance.pk)
        instance._old_api_token = old_team.api_token  # type: ignore[attr-defined]
    except Team.DoesNotExist:
        pass


def _update_cache_on_save(sender: type[Team], instance: Team, created: bool, **kwargs: Any) -> None:
    if not settings.FLAGS_REDIS_URL:
        return

    # Pop, don't peek: a stale stash left on the instance would clear the wrong
    # token on the next save (see _capture_old_api_token).
    old_api_token = instance.__dict__.pop("_old_api_token", None)
    rotated = bool(old_api_token and old_api_token != instance.api_token)

    def enqueue_task() -> None:
        try:
            update_team_llm_gateway_policy_cache_task.delay(instance.id)
            if rotated:
                # Same on-commit flow as the refresh so the old cache entry
                # disappears the moment the rotated token becomes live.
                kinds = ["redis"] if settings.TEST else None
                clear_team_llm_gateway_policy_cache(old_api_token, kinds=kinds)
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
    pre_save.connect(_capture_old_api_token, sender=Team)
    post_save.connect(_update_cache_on_save, sender=Team)
    pre_delete.connect(_clear_cache_on_delete, sender=Team)
