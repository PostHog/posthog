from __future__ import annotations

import pytest

from django.conf import settings

from temporalio import activity, workflow

from products.conversations.backend.temporal.plain_import.activities import (
    EnumerateThreadsInput,
    EnumerateThreadsOutput,
    UpdateJobProgressInput,
    UpdateJobStatusInput,
)
from products.conversations.backend.temporal.plain_import.constants import CONTINUE_AS_NEW_AFTER_PAGES
from products.conversations.backend.temporal.plain_import.workflows import (
    PlainImportBatchWorkflowInput,
    PlainImportCoordinatorInput,
    PlainImportCoordinatorOutput,
    PlainImportCoordinatorWorkflow,
)

TOTAL_PAGES = CONTINUE_AS_NEW_AFTER_PAGES + 5


def _page_from_cursor(cursor: str | None) -> int:
    return 0 if cursor is None else int(cursor)


@activity.defn(name="plain_import_enumerate_threads_activity")
async def _fake_enumerate(input: EnumerateThreadsInput) -> EnumerateThreadsOutput:
    page = _page_from_cursor(input.cursor)
    return EnumerateThreadsOutput(
        thread_ids=[f"t_{1000 + page}"],
        next_cursor=str(page + 1),
        end_of_stream=(page + 1 >= TOTAL_PAGES),
    )


@activity.defn(name="plain_import_update_job_progress_activity")
async def _fake_progress(input: UpdateJobProgressInput) -> None:
    return None


@activity.defn(name="plain_import_update_job_status_activity")
async def _fake_status(input: UpdateJobStatusInput) -> None:
    return None


@workflow.defn(name="plain-import-batch")
class _StubBatchWorkflow:
    @workflow.run
    async def run(self, input: PlainImportBatchWorkflowInput) -> PlainImportCoordinatorOutput:
        return PlainImportCoordinatorOutput(imported=len(input.thread_ids), skipped=0, failed=0)


class TestPlainImportCoordinatorContinueAsNew:
    @pytest.mark.asyncio
    async def test_import_continues_past_continue_as_new_boundary(self) -> None:
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        task_queue = settings.VIDEO_EXPORT_TASK_QUEUE

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[PlainImportCoordinatorWorkflow, _StubBatchWorkflow],
                activities=[_fake_enumerate, _fake_progress, _fake_status],
            ):
                result = await env.client.execute_workflow(
                    PlainImportCoordinatorWorkflow.run,
                    PlainImportCoordinatorInput(job_id="job-1", team_id=1, task_queue=task_queue),
                    id="test-plain-import-can",
                    task_queue=task_queue,
                )

        assert result.imported == TOTAL_PAGES
