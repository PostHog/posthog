"""
Celery tasks + Django signal handlers for the llm-gateway policy cache.

Independent of the team_metadata cache pipeline so the two caches can fail
(or be rolled back) without affecting each other.
"""

from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

import structlog
from celery import shared_task

from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.storage.team_llm_gateway_policy_cache import (
    clear_team_llm_gateway_policy_cache,
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


@receiver(post_save, sender=Team)
def update_team_llm_gateway_policy_cache_on_save(
    sender: type[Team], instance: Team, created: bool, **kwargs: Any
) -> None:
    if not settings.FLAGS_REDIS_URL:
        return

    def enqueue_task() -> None:
        try:
            update_team_llm_gateway_policy_cache_task.delay(instance.id)
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
