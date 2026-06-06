"""
Celery tasks for the llm-gateway policy cache.

Independent of the team_metadata cache pipeline so the two caches can fail
(or be rolled back) without affecting each other. The signal handlers that
drive these tasks on Team changes live in
posthog/storage/team_llm_gateway_policy_signal_handlers.py.
"""

import time

from django.conf import settings

import structlog
from celery import shared_task

from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.storage.team_llm_gateway_policy_cache import (
    get_cache_stats,
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
            namespace="team_metadata", cache_name="llm_gateway_policy", operation="update", result="failure"
        ).inc()
        return

    success = update_team_llm_gateway_policy_cache(team)
    HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
        namespace="team_metadata",
        cache_name="llm_gateway_policy",
        operation="update",
        result="success" if success else "failure",
    ).inc()


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_expiring_llm_gateway_policy_cache_entries() -> None:
    """
    Hourly task that refreshes policy cache entries whose TTL falls below the
    threshold, so simultaneous expiry of the 7-day TTL across the team pool
    cannot cause a DB-lookup spike.
    """
    if not settings.AI_GATEWAY_REDIS_URL:
        logger.info("AI gateway Redis URL not set, skipping llm-gateway policy cache refresh")
        return

    start_time = time.time()
    try:
        successful, failed = refresh_expiring_caches(ttl_threshold_hours=24)
        # get_cache_stats also pushes coverage/TTL gauges to Prometheus, matching
        # the team_metadata refresh task so the policy cache is observable too.
        stats_after = get_cache_stats()
        logger.info(
            "Completed llm-gateway policy cache refresh",
            successful_refreshes=successful,
            failed_refreshes=failed,
            total_cached=stats_after.get("total_cached", 0),
            cache_coverage=stats_after.get("cache_coverage", "unknown"),
            ttl_distribution=stats_after.get("ttl_distribution", {}),
            duration_seconds=time.time() - start_time,
        )
    except Exception as e:
        logger.exception(
            "Failed to complete llm-gateway policy cache refresh",
            error=str(e),
            duration_seconds=time.time() - start_time,
        )
        raise
