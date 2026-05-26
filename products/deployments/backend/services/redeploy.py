"""Trigger a new deployment at the same commit as a prior one."""

from __future__ import annotations

from ..adapters import CloudflareAdapter, GitHubAdapter, WorkflowAdapter
from ..domain.trigger import TriggerKind
from ..models import Deployment
from . import create_deployment


def execute(
    *,
    deployment_id: str,
    team_id: int,
    triggered_by_user_id: int | None,
    cloudflare: CloudflareAdapter | None = None,
    github: GitHubAdapter | None = None,
    workflow: WorkflowAdapter | None = None,
) -> Deployment:
    source = Deployment.objects.select_related("project").get(pk=deployment_id, team_id=team_id)
    return create_deployment.execute(
        create_deployment.CreateDeploymentInput(
            project_id=str(source.project_id),
            team_id=team_id,
            triggered_by_user_id=triggered_by_user_id,
            trigger_kind=TriggerKind.REDEPLOY,
            commit_sha=source.commit_sha or None,
            branch=source.branch or None,
            triggered_by_deployment_id=str(source.pk),
        ),
        cloudflare=cloudflare,
        github=github,
        workflow=workflow,
    )
