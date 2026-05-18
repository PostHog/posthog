"""Temporal workflow that drives a single deployment build.

Orchestrates the stub activities in `activities.py`. Real build work
(clone / install / build / upload) is stubbed at the activity level
pending hogland integration — this file shouldn't change when that
lands; only the underlying activities will.

The workflow id is `deployment-{deployment_id}` (set by the Django-side
`TemporalWorkflowAdapter.start_build`). The workflow type is
`"deployment-build"`.

Each activity gets its own retry policy:
- Initialize / mark_ready / mark_failed / start_building → API calls
  to ourselves, retry liberally.
- Build steps (clone / install / build / upload) → retry once, since
  they're stubs today but will run real user code in a sandbox once
  hogland lands. Retrying a flaky `npm install` is fine; retrying a
  build that hit a real compile error wastes minutes.

On any activity failure, the workflow posts an `ERROR` transition with
the right `error_step` and re-raises so Temporal records the run as
failed.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from ..domain.contracts import BuildInput
from ..domain.trigger import ErrorStep
from .activities import (
    MarkFailedInput,
    MarkReadyInput,
    StepInput,
    build_site,
    clone_repo,
    initialize_build,
    install_dependencies,
    mark_failed,
    mark_ready,
    start_building,
    upload_artifacts,
)

# API-call activities (`initialize`, `start_building`, `mark_*`) are
# cheap idempotent posts to the internal HTTP API. Build-step activities
# do real work and are expensive to retry. Different retry profiles.
_API_RETRY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=1))
_BUILD_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=2))

_API_TIMEOUT = timedelta(seconds=30)
_BUILD_TIMEOUT = timedelta(minutes=10)


@workflow.defn(name="deployment-build")
class DeploymentBuildWorkflow:
    """One run per Deployment row.

    Posts status transitions through QUEUED → INITIALIZING → BUILDING →
    READY (or ERROR on any failure). Activities post to the internal
    API; this workflow never writes to the DB directly.
    """

    @workflow.run
    async def run(self, payload: BuildInput) -> None:
        step = StepInput(
            deployment_id=payload.deployment_id,
            cloudflare_project_name=payload.cloudflare_project_name,
            repo_url=payload.repo_url,
            branch=payload.branch,
            commit_sha=payload.commit_sha,
            output_dir=payload.output_dir,
            github_access_token=payload.github_access_token,
            build_command=payload.build_command,
        )

        # `current_step` tracks which build phase is in flight so we
        # can mark_failed with the right error_step if anything raises.
        current_step = ErrorStep.DISPATCH
        try:
            await workflow.execute_activity(
                initialize_build, step, start_to_close_timeout=_API_TIMEOUT, retry_policy=_API_RETRY
            )

            current_step = ErrorStep.CLONE
            await workflow.execute_activity(
                clone_repo, step, start_to_close_timeout=_BUILD_TIMEOUT, retry_policy=_BUILD_RETRY
            )

            current_step = ErrorStep.INSTALL
            await workflow.execute_activity(
                install_dependencies, step, start_to_close_timeout=_BUILD_TIMEOUT, retry_policy=_BUILD_RETRY
            )

            # `start_building` is the gateway to the BUILD phase — a
            # failure transitioning into building should report
            # `error_step=build`, not `install`.
            current_step = ErrorStep.BUILD
            await workflow.execute_activity(
                start_building, step, start_to_close_timeout=_API_TIMEOUT, retry_policy=_API_RETRY
            )

            await workflow.execute_activity(
                build_site, step, start_to_close_timeout=_BUILD_TIMEOUT, retry_policy=_BUILD_RETRY
            )

            current_step = ErrorStep.PUBLISH
            deployment_url = await workflow.execute_activity(
                upload_artifacts, step, start_to_close_timeout=_BUILD_TIMEOUT, retry_policy=_BUILD_RETRY
            )

            await workflow.execute_activity(
                mark_ready,
                MarkReadyInput(
                    deployment_id=payload.deployment_id,
                    deployment_url=deployment_url,
                    # No CF deployment id yet — populated once the real
                    # upload activity returns one.
                    cloudflare_deployment_id=None,
                ),
                start_to_close_timeout=_API_TIMEOUT,
                retry_policy=_API_RETRY,
            )
        except ActivityError as err:
            await workflow.execute_activity(
                mark_failed,
                MarkFailedInput(
                    deployment_id=payload.deployment_id,
                    error_message=str(err),
                    error_step=current_step,
                ),
                start_to_close_timeout=_API_TIMEOUT,
                retry_policy=_API_RETRY,
            )
            raise
