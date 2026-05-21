"""
Celery tasks + Django signal handlers for the llm-gateway policy cache.

Independent of the team_metadata cache pipeline so the two caches can fail
(or be rolled back) without affecting each other.
"""

import time
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

import structlog
from celery import shared_task

from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.storage.team_llm_gateway_policy_cache import (
    clear_team_llm_gateway_policy_cache,
    refresh_expiring_caches,
    update_team_llm_gateway_policy_cache,
)
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def update_team_llm_gateway_policy_cache_task(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.debug("Team does not exist for llm-gateway policy cache update", team_id=team_id)
        HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
            namespace="team_metadata", operation="update_llm_gateway", result="failure"
        ).inc()
        return

    success = update_team_llm_gateway_policy_cache(team)
    HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
        namespace="team_metadata",
        operation="update_llm_gateway",
        result="success" if success else "failure",
    ).inc()


@receiver(pre_save, sender=Team)
def capture_old_api_token_for_llm_gateway_policy(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    """
    Stash the previous api_token on the instance so the post_save handler can
    invalidate the cache entry keyed by the OLD token after an api_token
    rotation. Without this, a holder of the rotated token would keep hitting
    the gateway successfully until the stale cache entry's 7-day TTL expires.
    """
    if not instance.pk or instance._state.adding:
        return

    # Some other handler may have already captured this; don't double-fetch.
    if "_old_api_token" in instance.__dict__:
        return

    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "api_token" not in update_fields:
        return

    try:
        old_team = Team.objects.only("api_token").get(pk=instance.pk)
        instance._old_api_token = old_team.api_token  # type: ignore[attr-defined]
    except Team.DoesNotExist:
        pass


@receiver(post_save, sender=Team)
def update_team_llm_gateway_policy_cache_on_save(
    sender: type[Team], instance: Team, created: bool, **kwargs: Any
) -> None:
    if not settings.FLAGS_REDIS_URL:
        return

    old_api_token = getattr(instance, "_old_api_token", None)
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
                namespace="team_metadata", operation="enqueue_llm_gateway", result="failure"
            ).inc()
            logger.exception(
                "Failed to enqueue llm-gateway policy cache update",
                team_id=instance.id,
                error=str(e),
            )

    transaction.on_commit(enqueue_task)


@receiver(pre_delete, sender=Team)
def clear_team_llm_gateway_policy_cache_on_delete(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    if not settings.FLAGS_REDIS_URL:
        return

    kinds = ["redis"] if settings.TEST else None
    clear_team_llm_gateway_policy_cache(instance, kinds=kinds)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_expiring_llm_gateway_policy_cache_entries() -> None:
    """
    Hourly task that refreshes policy cache entries whose TTL falls below the
    threshold, so simultaneous expiry of the 7-day TTL across the team pool
    cannot cause a DB-lookup spike.
    """
    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping llm-gateway policy cache refresh")
        return

    start_time = time.time()
    try:
        successful, failed = refresh_expiring_caches(ttl_threshold_hours=24)
        logger.info(
            "Completed llm-gateway policy cache refresh",
            successful_refreshes=successful,
            failed_refreshes=failed,
            duration_seconds=time.time() - start_time,
        )
    except Exception as e:
        logger.exception(
            "Failed to complete llm-gateway policy cache refresh",
            error=str(e),
            duration_seconds=time.time() - start_time,
        )
        raise
