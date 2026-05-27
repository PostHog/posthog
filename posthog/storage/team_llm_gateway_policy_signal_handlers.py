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
from django.db.models.signals import post_init, post_save, pre_delete

import structlog

from posthog.models.team import Team
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.storage.team_llm_gateway_policy_cache import clear_team_llm_gateway_policy_cache
from posthog.tasks.team_llm_gateway_policy import update_team_llm_gateway_policy_cache_task

logger = structlog.get_logger(__name__)

# Stashes the api_token a Team instance was loaded/constructed with, so post_save
# can detect a rotation without re-reading the row from the DB.
_LOADED_API_TOKEN_ATTR = "_llm_gateway_loaded_api_token"


def _snapshot_api_token(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    """
    Record the instance's current api_token on post_init so the post_save handler
    can spot a rotation by comparison. This is the from_db-snapshot pattern: it
    adds no query (api_token has a field default, so it is populated at __init__),
    unlike a pre_save SELECT which would add one DB read to every Team.save().
    Skip when api_token is deferred (e.g. a .only() fetch) so we never trigger a
    lazy load.
    """
    if "api_token" in instance.get_deferred_fields():
        return
    instance.__dict__[_LOADED_API_TOKEN_ATTR] = instance.api_token


def _update_cache_on_save(sender: type[Team], instance: Team, created: bool, **kwargs: Any) -> None:
    if not settings.FLAGS_REDIS_URL:
        return

    old_api_token: str | None = instance.__dict__.get(_LOADED_API_TOKEN_ATTR)
    rotated = bool(old_api_token and old_api_token != instance.api_token)
    # Re-snapshot so a kept-alive instance saved again (A->B->C) compares against
    # the just-saved token instead of clearing the original twice.
    instance.__dict__[_LOADED_API_TOKEN_ATTR] = instance.api_token

    def enqueue_task() -> None:
        try:
            update_team_llm_gateway_policy_cache_task.delay(instance.id)
            if rotated and old_api_token is not None:
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
    post_init.connect(_snapshot_api_token, sender=Team)
    post_save.connect(_update_cache_on_save, sender=Team)
    pre_delete.connect(_clear_cache_on_delete, sender=Team)
