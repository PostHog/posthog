"""Create a new Deployment row, dispatch its build workflow.

The partial unique index `one_active_deployment_per_project` makes
concurrent POSTs race-safe at the DB layer: the second insert raises
IntegrityError, which the viewset translates to HTTP 409 Conflict.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction

from ..adapters import (
    CloudflareAdapter,
    GitHubAdapter,
    WorkflowAdapter,
    get_cloudflare_adapter,
    get_github_adapter,
    get_workflow_adapter,
)
from ..domain.contracts import BuildInput
from ..domain.trigger import TriggerKind
from ..models import Deployment, DeploymentProject


class ActiveDeploymentExists(Exception):
    """Raised when a project already has a non-terminal deployment in flight.

    The viewset catches this and returns HTTP 409 with the in-flight
    deployment ID.
    """

    def __init__(self, active_deployment_id: str) -> None:
        self.active_deployment_id = active_deployment_id
        super().__init__(f"Project already has an active deployment: {active_deployment_id}")


@dataclass(frozen=True)
class CreateDeploymentInput:
    project_id: str
    team_id: int
    triggered_by_user_id: int | None
    trigger_kind: TriggerKind
    commit_sha: str | None
    branch: str | None
    triggered_by_deployment_id: str | None = None


def execute(
    payload: CreateDeploymentInput,
    *,
    cloudflare: CloudflareAdapter | None = None,
    github: GitHubAdapter | None = None,
    workflow: WorkflowAdapter | None = None,
) -> Deployment:
    project = DeploymentProject.objects.get(id=payload.project_id, team_id=payload.team_id)

    # Resolve commit metadata up-front when possible. The build worker will
    # also resolve HEAD-of-branch in `resolve_commit_sha`, but pre-resolving
    # lets the list scene render real commit messages before the worker
    # picks up the workflow.
    branch = payload.branch or project.default_branch
    gh = github or get_github_adapter()
    if payload.commit_sha:
        commit = gh.get_commit(repo_url=project.repo_url, sha=payload.commit_sha, pat=project.github_pat)
    else:
        commit = gh.head_of_branch(repo_url=project.repo_url, branch=branch, pat=project.github_pat)

    try:
        with transaction.atomic():
            deployment = Deployment.objects.create(
                project=project,
                team_id=payload.team_id,
                triggered_by_user_id=payload.triggered_by_user_id,
                triggered_by_deployment_id=payload.triggered_by_deployment_id,
                trigger_kind=payload.trigger_kind.value,
                status=Deployment.Status.QUEUED,
                commit_sha=commit.sha,
                commit_message=commit.message,
                commit_author_name=commit.author_name,
                commit_author_email=commit.author_email,
                repo_url=project.repo_url,
                branch=commit.branch,
            )
    except IntegrityError as exc:
        # Race: another POST landed first. Surface the in-flight deployment
        # so the FE can poll its detail endpoint instead of retrying.
        if "one_active_deployment_per_project" in str(exc):
            in_flight = (
                Deployment.objects.filter(
                    project_id=payload.project_id,
                    team_id=payload.team_id,
                    status__in=Deployment.NON_TERMINAL_STATUSES,
                )
                .values_list("id", flat=True)
                .first()
            )
            raise ActiveDeploymentExists(str(in_flight) if in_flight else "")
        raise

    # Hand off to the build worker. Persist the workflow handle so cancel()
    # can target the right run later.
    wf = workflow or get_workflow_adapter()
    cf = cloudflare or get_cloudflare_adapter()  # noqa: F841 — held for future provisioning checks
    handle = wf.start_build(
        workflow_input=BuildInput(
            deployment_id=deployment.id,
            project_id=project.id,
            team_id=payload.team_id,
            repo_url=project.repo_url,
            branch=commit.branch,
            commit_sha=commit.sha,
            github_pat=project.github_pat,
            build_command=project.build_command,
            output_dir=project.output_dir,
            framework=project.framework,
            inject_posthog_snippet=project.inject_posthog_snippet,
            cloudflare_project_name=project.cloudflare_project_name,
            trigger_kind=payload.trigger_kind,
        )
    )
    Deployment.objects.filter(pk=deployment.pk).update(
        temporal_workflow_id=handle.workflow_id,
        temporal_run_id=handle.run_id,
    )
    deployment.refresh_from_db()
    return deployment
