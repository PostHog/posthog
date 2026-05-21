"""Trigger a rollback deployment: a new row pointing at the target deployment.

The actual Cloudflare rollback is performed by the build worker (it calls
the Cloudflare adapter's `rollback` from inside the workflow). When the
worker finishes and posts `ready`, `update_status` flips
`DeploymentProject.current_deployment` to this rollback row.
"""

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
    target = Deployment.objects.select_related("project").get(pk=deployment_id, team_id=team_id)
    return create_deployment.execute(
        create_deployment.CreateDeploymentInput(
            project_id=str(target.project_id),
            team_id=team_id,
            triggered_by_user_id=triggered_by_user_id,
            trigger_kind=TriggerKind.ROLLBACK,
            commit_sha=target.commit_sha or None,
            branch=target.branch or None,
            triggered_by_deployment_id=str(target.pk),
        ),
        cloudflare=cloudflare,
        github=github,
        workflow=workflow,
    )
