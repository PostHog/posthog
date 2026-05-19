"""Create a new Deployment row, dispatch its build workflow.

The partial unique index `one_active_deployment_per_project` makes
concurrent POSTs race-safe at the DB layer: the second insert raises
IntegrityError, which the viewset translates to HTTP 409 Conflict.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog

from posthog.models.integration import Integration

from ..adapters import (
    CloudflareAdapter,
    GitHubAdapter,
    WorkflowAdapter,
    get_cloudflare_adapter,
    get_github_adapter,
    get_workflow_adapter,
)
from ..domain.contracts import BuildInput
from ..domain.trigger import ErrorStep, TriggerKind
from ..models import Deployment, DeploymentProject

logger = structlog.get_logger(__name__)


class ActiveDeploymentExists(Exception):
    """Raised when a project already has a non-terminal deployment in flight.

    The viewset catches this and returns HTTP 409 with the in-flight
    deployment ID.
    """

    def __init__(self, active_deployment_id: str) -> None:
        self.active_deployment_id = active_deployment_id
        super().__init__(f"Project already has an active deployment: {active_deployment_id}")


class WorkflowDispatchFailed(Exception):
    """Raised when the build workflow couldn't be dispatched.

    The deployment row has already been marked ERROR at this point —
    callers should surface a 502 to the client. The row carries
    `error_step=dispatch` and `error_message` describing the failure so
    operators can audit it.
    """

    def __init__(self, deployment_id: str, cause: BaseException) -> None:
        self.deployment_id = deployment_id
        self.__cause__ = cause
        super().__init__(f"Failed to start build workflow for deployment {deployment_id}: {cause}")


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

    # Resolve the GitHub access token from the project's Integration row, if any.
    # The token is short-lived (GitHub App installation tokens expire after ~1h);
    # we read whatever's currently stored in `sensitive_config` — refreshing is
    # owned by the integration framework, not this service. A null token means
    # public-repo access or a Null adapter in tests.
    access_token = _resolve_github_access_token(project.github_integration_id, project.team_id)

    # Resolve commit metadata up-front when possible. The build worker will
    # also resolve HEAD-of-branch in `resolve_commit_sha`, but pre-resolving
    # lets the list scene render real commit messages before the worker
    # picks up the workflow.
    branch = payload.branch or project.default_branch
    gh = github or get_github_adapter()
    if payload.commit_sha:
        commit = gh.get_commit(repo_url=project.repo_url, sha=payload.commit_sha, access_token=access_token)
    else:
        commit = gh.head_of_branch(repo_url=project.repo_url, branch=branch, access_token=access_token)

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
                    project=project,
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
    #
    # The row is already committed in QUEUED state by this point. If
    # `start_build` raises (e.g. Temporal unreachable), the row would
    # otherwise sit QUEUED forever with no workflow id — no worker to
    # advance it and `cancel.execute` would have nothing to signal. So
    # we flip it to ERROR(error_step=dispatch) on failure and raise a
    # typed exception the view can map to 502.
    wf = workflow or get_workflow_adapter()
    cf = cloudflare or get_cloudflare_adapter()  # noqa: F841 — held for future provisioning checks
    try:
        handle = wf.start_build(
            workflow_input=BuildInput(
                deployment_id=deployment.id,
                project_id=project.id,
                team_id=payload.team_id,
                repo_url=project.repo_url,
                branch=commit.branch,
                commit_sha=commit.sha,
                github_access_token=access_token,
                build_command=project.build_command,
                output_dir=project.output_dir,
                framework=project.framework,
                inject_posthog_snippet=project.inject_posthog_snippet,
                cloudflare_project_name=project.cloudflare_project_name,
                trigger_kind=payload.trigger_kind,
            )
        )
    except Exception as exc:
        logger.exception(
            "create_deployment.workflow_dispatch_failed",
            deployment_id=str(deployment.pk),
            error=str(exc),
        )
        # Direct .update() instead of `update_status.execute` so we don't
        # walk the state machine for a row that never got off QUEUED —
        # `assert_valid(QUEUED, ERROR)` is valid but the side-effect
        # scheduling in update_status (finalize_failure → $exception) is
        # noise for a dispatch failure that never produced any build
        # output. Operators see the ERROR row + the structlog event.
        Deployment.objects.filter(pk=deployment.pk).update(
            status=Deployment.Status.ERROR.value,
            error_step=ErrorStep.DISPATCH.value,
            error_message=f"Failed to dispatch build workflow: {exc}",
            finished_at=timezone.now(),
        )
        raise WorkflowDispatchFailed(str(deployment.pk), exc) from exc

    Deployment.objects.filter(pk=deployment.pk).update(
        temporal_workflow_id=handle.workflow_id,
        temporal_run_id=handle.run_id,
    )
    deployment.refresh_from_db()
    return deployment


def _resolve_github_access_token(integration_id: int | None, team_id: int) -> str | None:
    if integration_id is None:
        return None
    try:
        integration = Integration.objects.get(id=integration_id, kind="github", team_id=team_id)
    except Integration.DoesNotExist:
        # Row was deleted, never existed, or belongs to a different team. Treat
        # as "no creds" so the adapter can still attempt unauthenticated
        # public-repo access and surface a clean GitHubError if the repo is
        # private. Filtering by team_id closes the IDOR window where a stale
        # github_integration_id (e.g. left over from a moved project) could
        # otherwise resolve to another team's GitHub App token.
        logger.warning(
            "create_deployment.integration_missing",
            integration_id=integration_id,
            team_id=team_id,
        )
        return None
    token = integration.sensitive_config.get("access_token")
    return str(token) if token else None
