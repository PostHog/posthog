"""Helpers to start Plain import Temporal workflows."""

from __future__ import annotations

from django.conf import settings

from temporalio.common import WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

from products.conversations.backend.temporal.plain_import.constants import WORKFLOW_ID_PREFIX
from products.conversations.backend.temporal.plain_import.workflows import (
    PlainImportCoordinatorInput,
    PlainImportCoordinatorWorkflow,
)


async def start_plain_import_workflow(
    *,
    job_id: str,
    team_id: int,
    dry_run: bool = False,
    max_tickets: int | None = None,
    default_email_channel_id: str | None = None,
) -> tuple[str, str | None]:
    client = await async_connect()
    workflow_id = f"{WORKFLOW_ID_PREFIX}-{team_id}-{job_id}"
    task_queue = settings.VIDEO_EXPORT_TASK_QUEUE
    handle = await client.start_workflow(
        PlainImportCoordinatorWorkflow.run,
        PlainImportCoordinatorInput(
            job_id=job_id,
            team_id=team_id,
            dry_run=dry_run,
            max_tickets=max_tickets,
            default_email_channel_id=default_email_channel_id,
            task_queue=task_queue,
        ),
        id=workflow_id,
        task_queue=task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    return workflow_id, handle.run_id
