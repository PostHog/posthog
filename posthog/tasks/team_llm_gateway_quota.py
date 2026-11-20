"""Celery tasks that project the per-team quota blob the Go ai-gateway's credit-bucket gate reads."""

import time

from django.conf import settings

import structlog
from celery import shared_task

from posthog.models.organization import Organization
from posthog.storage.team_llm_gateway_quota_cache import (
    project_org_quota,
    project_teams_quota_by_token,
    reconcile_quota_projection,
)
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def project_org_llm_gateway_quota_task(organization_id: str) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    try:
        organization = Organization.objects.get(id=organization_id)  # nosemgrep: celery-task-team-scope-audit
    except Organization.DoesNotExist:
        logger.debug("Organization does not exist for llm-gateway quota projection", organization_id=organization_id)
        return
    written = project_org_quota(organization)
    logger.info(
        "Projected llm-gateway quota for organization",
        organization_id=organization_id,
        is_active=organization.is_active,
        blobs_written=written,
    )


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def project_teams_llm_gateway_quota_task(tokens: list[str]) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    written = project_teams_quota_by_token(tokens)
    logger.info("Projected llm-gateway quota for teams", teams=len(tokens), blobs_written=written)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def reconcile_llm_gateway_quota_projection() -> None:
    """Heals a missed signal, an expiring deactivated-org blob, or a stray blob within a tick."""
    if not settings.AI_GATEWAY_REDIS_URL:
        logger.info("AI gateway Redis URL not set, skipping llm-gateway quota projection reconcile")
        return
    start_time = time.time()
    try:
        counts = reconcile_quota_projection()
        logger.info(
            "Completed llm-gateway quota projection reconcile",
            **counts,
            duration_seconds=time.time() - start_time,
        )
    except Exception as e:
        logger.exception(
            "Failed to complete llm-gateway quota projection reconcile",
            error=str(e),
            duration_seconds=time.time() - start_time,
        )
        raise
