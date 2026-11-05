"""Celery tasks for the llm-gateway organization entry. See posthog/storage/team_llm_gateway_org_cache.py."""

import time

from django.conf import settings

import structlog
from celery import shared_task

from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.storage.team_llm_gateway_org_cache import (
    get_cache_stats,
    refresh_expiring_caches,
    update_organization_llm_gateway_org_cache,
    update_team_llm_gateway_org_cache,
)
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def update_team_llm_gateway_org_cache_task(team_id: int) -> None:
    team = Team.objects.filter(id=team_id).only("id", "organization_id").first()
    if team is None:
        return
    update_team_llm_gateway_org_cache(team)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def update_organization_llm_gateway_org_cache_task(organization_id: str) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    written = update_organization_llm_gateway_org_cache(organization_id)
    logger.info("Projected the llm-gateway organization entry", organization_id=organization_id, teams=written)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def refresh_expiring_llm_gateway_org_cache_entries() -> None:
    """Hourly: rewrite entries whose TTL falls below a day, so none lapses while its team can spend."""
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    start_time = time.time()
    counts = refresh_expiring_caches(ttl_threshold_hours=24)
    stats = get_cache_stats()
    logger.info(
        "Completed llm-gateway organization entry refresh",
        successful_refreshes=counts.successful,
        failed_refreshes=counts.failed,
        total_cached=stats.get("total_cached", 0),
        cache_coverage=stats.get("cache_coverage", "unknown"),
        duration_seconds=time.time() - start_time,
    )
