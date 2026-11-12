from __future__ import annotations

import pytest

from django.conf import settings

from temporalio import activity, workflow

from products.conversations.backend.temporal.intercom_import.activities import (
    EnumerateConversationsInput,
    EnumerateConversationsOutput,
    UpdateJobProgressInput,
    UpdateJobStatusInput,
)
from products.conversations.backend.temporal.intercom_import.constants import CONTINUE_AS_NEW_AFTER_PAGES
from products.conversations.backend.temporal.intercom_import.workflows import (
    IntercomImportBatchWorkflowInput,
    IntercomImportCoordinatorInput,
    IntercomImportCoordinatorOutput,
    IntercomImportCoordinatorWorkflow,
)

# Enough pages to cross exactly one continue-as-new boundary, one conversation per page.
TOTAL_PAGES = CONTINUE_AS_NEW_AFTER_PAGES + 5


@activity.defn(name="intercom_import_enumerate_conversations_activity")
async def _fake_enumerate(input: EnumerateConversationsInput) -> EnumerateConversationsOutput:
    page = 0 if input.cursor is None else int(input.cursor)
    next_page = page + 1
    return EnumerateConversationsOutput(
        conversation_ids=[str(1000 + page)],
        next_cursor=None if next_page >= TOTAL_PAGES else str(next_page),
    )


@activity.defn(name="intercom_import_update_job_progress_activity")
async def _fake_progress(input: UpdateJobProgressInput) -> None:
    return None


@activity.defn(name="intercom_import_update_job_status_activity")
async def _fake_status(input: UpdateJobStatusInput) -> None:
    return None


@workflow.defn(name="intercom-import-batch")
class _StubBatchWorkflow:
    """Reports one import per conversation it receives, so a batch that never runs (child-id
    collision swallowed as WorkflowAlreadyStartedError) contributes nothing to the total."""

    @workflow.run
    async def run(self, input: IntercomImportBatchWorkflowInput) -> IntercomImportCoordinatorOutput:
        return IntercomImportCoordinatorOutput(imported=len(input.conversation_ids), skipped=0, failed=0)


class TestIntercomImportCoordinatorContinueAsNew:
    @pytest.mark.asyncio
    async def test_import_continues_past_continue_as_new_boundary(self) -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        task_queue = settings.VIDEO_EXPORT_TASK_QUEUE

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[IntercomImportCoordinatorWorkflow, _StubBatchWorkflow],
                activities=[_fake_enumerate, _fake_progress, _fake_status],
            ):
                result = await env.client.execute_workflow(
                    IntercomImportCoordinatorWorkflow.run,
                    IntercomImportCoordinatorInput(job_id="job-1", team_id=1, task_queue=task_queue),
                    id="test-intercom-import-can",
                    task_queue=task_queue,
                )

        assert result.imported == TOTAL_PAGES
