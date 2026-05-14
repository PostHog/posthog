"""Activities for the Deployments build workflow.

This is the v1 scaffolding: every activity posts an event/transition so
the timeline + state machine work end-to-end, but the actual build
steps (clone, install, build, upload) are stubs. The real work lives
behind hogland sandbox provisioning in a follow-up PR — see
`.notes/deployments-substrate.md` for why we run user code in a
Firecracker microVM, not directly in this worker pod.

Each activity returns quickly. Temporal handles retries; we don't
retry inside.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from temporalio import activity

from ..domain.status import Status
from ..domain.trigger import ErrorStep
from .internal_api import post_event, post_transition


@dataclass(frozen=True)
class StepInput:
    """Common shape for build-step activities.

    Carries every field from `BuildInput` that any activity may need —
    `github_access_token` and `build_command` are unused by the current
    stub activities but the real `clone_repo` / `build_site` will read
    them. Locking the shape in now means swapping the stubs for real
    activities is a body-only change, not a signature change.
    """

    deployment_id: UUID
    cloudflare_project_name: str
    repo_url: str
    branch: str
    commit_sha: str
    output_dir: str
    github_access_token: str | None
    build_command: str | None


@dataclass(frozen=True)
class MarkReadyInput:
    deployment_id: UUID
    deployment_url: str
    cloudflare_deployment_id: str | None


@dataclass(frozen=True)
class MarkFailedInput:
    deployment_id: UUID
    error_message: str
    error_step: ErrorStep


# Stub sleep durations — keep small enough that test runs don't drag,
# big enough that the timeline UI shows something happening when this
# is running against a real cluster.
_STUB_STEP_SLEEP_SECONDS = 0.5


@activity.defn(name="deployment-build.initialize")
async def initialize_build(payload: StepInput) -> None:
    """Move the deployment from QUEUED to INITIALIZING."""
    await post_transition(deployment_id=payload.deployment_id, status=Status.INITIALIZING)
    await post_event(
        deployment_id=payload.deployment_id,
        event_type="status_changed",
        payload={"to": Status.INITIALIZING.value},
    )


@activity.defn(name="deployment-build.clone")
async def clone_repo(payload: StepInput) -> None:
    """STUB: pretend to clone `payload.repo_url` at `payload.commit_sha`."""
    await post_event(
        deployment_id=payload.deployment_id,
        event_type="clone_started",
        payload={"repo_url": payload.repo_url, "branch": payload.branch, "commit_sha": payload.commit_sha},
    )
    await asyncio.sleep(_STUB_STEP_SLEEP_SECONDS)
    await post_event(deployment_id=payload.deployment_id, event_type="clone_complete")


@activity.defn(name="deployment-build.install")
async def install_dependencies(payload: StepInput) -> None:
    """STUB: pretend to install dependencies."""
    await post_event(deployment_id=payload.deployment_id, event_type="install_started")
    await asyncio.sleep(_STUB_STEP_SLEEP_SECONDS)
    await post_event(deployment_id=payload.deployment_id, event_type="install_complete")


@activity.defn(name="deployment-build.start_building")
async def start_building(payload: StepInput) -> None:
    """Move the deployment from INITIALIZING to BUILDING."""
    await post_transition(deployment_id=payload.deployment_id, status=Status.BUILDING)
    await post_event(
        deployment_id=payload.deployment_id,
        event_type="status_changed",
        payload={"to": Status.BUILDING.value},
    )


@activity.defn(name="deployment-build.build")
async def build_site(payload: StepInput) -> None:
    """STUB: pretend to run the build."""
    await post_event(deployment_id=payload.deployment_id, event_type="build_started")
    await asyncio.sleep(_STUB_STEP_SLEEP_SECONDS)
    await post_event(
        deployment_id=payload.deployment_id,
        event_type="build_complete",
        payload={"output_dir": payload.output_dir},
    )


@activity.defn(name="deployment-build.upload")
async def upload_artifacts(payload: StepInput) -> str:
    """STUB: pretend to upload to Cloudflare Pages.

    Returns a synthetic deployment URL so the workflow can complete.
    The real adapter will return Cloudflare's actual deployment URL
    once the upload step is implemented (hogland-side).
    """
    await post_event(deployment_id=payload.deployment_id, event_type="upload_started")
    await asyncio.sleep(_STUB_STEP_SLEEP_SECONDS)
    synthetic_url = f"https://{payload.cloudflare_project_name}.pages.dev"
    await post_event(
        deployment_id=payload.deployment_id,
        event_type="upload_complete",
        payload={"deployment_url": synthetic_url, "stub": True},
    )
    return synthetic_url


@activity.defn(name="deployment-build.mark_ready")
async def mark_ready(payload: MarkReadyInput) -> None:
    """Move the deployment from BUILDING to READY."""
    await post_transition(
        deployment_id=payload.deployment_id,
        status=Status.READY,
        deployment_url=payload.deployment_url,
        cloudflare_deployment_id=payload.cloudflare_deployment_id,
    )
    await post_event(
        deployment_id=payload.deployment_id,
        event_type="status_changed",
        payload={"to": Status.READY.value, "deployment_url": payload.deployment_url},
    )


@activity.defn(name="deployment-build.mark_failed")
async def mark_failed(payload: MarkFailedInput) -> None:
    """Move the deployment from a non-terminal status to ERROR.

    Best-effort: the workflow calls this in an exception handler. If
    posting the transition itself fails (e.g. internal API down), the
    activity raises and Temporal retries. If we exhaust retries, the
    workflow run is left in whatever non-terminal status it was in when
    the original error fired — a janitor sweep would need to catch that
    separately, but that's out of scope for v1.
    """
    await post_transition(
        deployment_id=payload.deployment_id,
        status=Status.ERROR,
        error_message=payload.error_message,
        error_step=payload.error_step,
    )
    await post_event(
        deployment_id=payload.deployment_id,
        event_type="status_changed",
        payload={
            "to": Status.ERROR.value,
            "error_step": payload.error_step.value,
            "error_message": payload.error_message,
        },
    )
