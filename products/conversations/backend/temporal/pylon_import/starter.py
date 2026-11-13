"""Helpers to start Pylon import Temporal workflows."""

from __future__ import annotations

from typing import Literal

from django.conf import settings

from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect

from products.conversations.backend.temporal.pylon_import.constants import WORKFLOW_ID_PREFIX
from products.conversations.backend.temporal.pylon_import.workflows import (
    PylonImportCoordinatorInput,
    PylonImportCoordinatorWorkflow,
)


def coordinator_workflow_id(*, team_id: int, job_id: str) -> str:
    return f"{WORKFLOW_ID_PREFIX}-{team_id}-{job_id}"


_WorkflowState = Literal["running", "closed", "missing", "unknown"]


async def _workflow_state(*, team_id: int, job_id: str) -> _WorkflowState:
    # A namespace that does not resolve answers NOT_FOUND for every workflow, so only a not-found
    # that names no namespace proves the workflow is missing.
    try:
        client = await async_connect()
        description = await client.get_workflow_handle(
            coordinator_workflow_id(team_id=team_id, job_id=job_id)
        ).describe()
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND and "namespace" not in error.message.lower():
            return "missing"
        return "unknown"
    except Exception:
        return "unknown"
    return "running" if description.status == WorkflowExecutionStatus.RUNNING else "closed"


async def pylon_import_workflow_exists(*, team_id: int, job_id: str) -> bool:
    """Whether Temporal has a workflow for this job, reading anything but a clean not-found as yes.

    Releasing a live job lets a second import start against it, which is worse than leaving a dead
    job blocked a while longer.
    """
    return await _workflow_state(team_id=team_id, job_id=job_id) != "missing"


async def pylon_import_workflow_is_running(*, team_id: int, job_id: str) -> bool:
    """Whether the job's workflow is still executing, reading an unclear answer as yes.

    Only a workflow that Temporal reports as closed or missing counts as stopped, for the same
    reason as above.
    """
    return await _workflow_state(team_id=team_id, job_id=job_id) in ("running", "unknown")


async def start_pylon_import_workflow(
    *,
    job_id: str,
    team_id: int,
    default_email_channel_id: str | None = None,
) -> tuple[str, str | None]:
    client = await async_connect()
    workflow_id = coordinator_workflow_id(team_id=team_id, job_id=job_id)
    task_queue = settings.VIDEO_EXPORT_TASK_QUEUE
    handle = await client.start_workflow(
        PylonImportCoordinatorWorkflow.run,
        PylonImportCoordinatorInput(
            job_id=job_id,
            team_id=team_id,
            default_email_channel_id=default_email_channel_id,
            task_queue=task_queue,
        ),
        id=workflow_id,
        task_queue=task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    return workflow_id, handle.run_id
