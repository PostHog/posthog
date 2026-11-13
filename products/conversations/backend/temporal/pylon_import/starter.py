"""Helpers to start Pylon import Temporal workflows."""

from __future__ import annotations

from django.conf import settings

from temporalio.common import WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

from products.conversations.backend.temporal.pylon_import.constants import WORKFLOW_ID_PREFIX
from products.conversations.backend.temporal.pylon_import.workflows import (
    PylonImportCoordinatorInput,
    PylonImportCoordinatorWorkflow,
)
from products.conversations.backend.temporal.ticket_import.workflow_state import workflow_exists, workflow_is_running


def coordinator_workflow_id(*, team_id: int, job_id: str) -> str:
    return f"{WORKFLOW_ID_PREFIX}-{team_id}-{job_id}"


async def pylon_import_workflow_exists(*, team_id: int, job_id: str) -> bool:
    return await workflow_exists(coordinator_workflow_id(team_id=team_id, job_id=job_id))


async def pylon_import_workflow_is_running(*, team_id: int, job_id: str) -> bool:
    return await workflow_is_running(coordinator_workflow_id(team_id=team_id, job_id=job_id))


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
