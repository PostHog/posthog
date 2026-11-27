"""Celery tasks for access_control."""

import structlog
from celery import shared_task

from posthog.celery_queues import CeleryQueue

from products.access_control.backend.facade import api

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def process_github_team_role_webhook(
    *,
    installation_id: str,
    action: str,
    github_org_login: str,
    github_team_id: int,
    github_team_slug: str,
    github_team_name: str,
) -> None:
    api.sync_single_github_team_webhook(
        installation_id=installation_id,
        action=action,
        github_org_login=github_org_login,
        github_team_id=github_team_id,
        github_team_slug=github_team_slug,
        github_team_name=github_team_name,
    )


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sync_organization_github_roles_task(organization_id: str) -> None:
    api.sync_organization_github_roles(organization_id=organization_id, interactive=False)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def sync_all_organization_github_roles() -> None:
    for organization_id in api.list_organizations_with_github_team_sync_candidates():
        try:
            sync_organization_github_roles_task.delay(str(organization_id))
        except Exception:
            logger.exception("access_control.github_role_sync.enqueue_failed", organization_id=str(organization_id))
