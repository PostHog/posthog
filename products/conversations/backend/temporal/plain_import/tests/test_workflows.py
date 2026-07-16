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


@activity.defn(name="plain_import_enumerate_threads_activity")
async def _fake_enumerate_single(input: EnumerateThreadsInput) -> EnumerateThreadsOutput:
    return EnumerateThreadsOutput(thread_ids=["only"], next_cursor=None, end_of_stream=True)


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


class TestPlainImportCoordinatorAwaitsExistingBatch:
    @pytest.mark.asyncio
    async def test_existing_child_counts_roll_up_instead_of_zero(self) -> None:
        # Regression: if a batch child id already exists (a still-running or completed prior
        # attempt), the coordinator must wait for that execution and roll up its real counts rather
        # than returning zeros — otherwise the cursor advances past a batch that was never counted.
        from unittest.mock import AsyncMock, patch

        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        from products.conversations.backend.temporal.plain_import import activities as plain_activities
        from products.conversations.backend.temporal.plain_import.activities import plain_import_await_batch_activity

        task_queue = settings.VIDEO_EXPORT_TASK_QUEUE

        async with await WorkflowEnvironment.start_time_skipping() as env:
            # The await activity connects via async_connect(); point it at the test server.
            with patch.object(plain_activities, "async_connect", new=AsyncMock(return_value=env.client)):
                async with Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[PlainImportCoordinatorWorkflow, _StubBatchWorkflow],
                    activities=[
                        _fake_enumerate_single,
                        _fake_progress,
                        _fake_status,
                        plain_import_await_batch_activity,
                    ],
                ):
                    # Pre-start and complete the exact child id the coordinator targets for page 1,
                    # window 0 — so its execute_child_workflow raises WorkflowAlreadyStartedError.
                    existing = await env.client.start_workflow(
                        _StubBatchWorkflow.run,
                        PlainImportBatchWorkflowInput(
                            job_id="job-await",
                            team_id=1,
                            thread_ids=["a", "b", "c", "d", "e", "f", "g"],
                        ),
                        id="plain-import-batch-job-await-1-0",
                        task_queue=task_queue,
                    )
                    assert (await existing.result()).imported == 7

                    result = await env.client.execute_workflow(
                        PlainImportCoordinatorWorkflow.run,
                        PlainImportCoordinatorInput(job_id="job-await", team_id=1, task_queue=task_queue),
                        id="test-plain-import-await",
                        task_queue=task_queue,
                    )

        # The enumerated page collides with the pre-existing child; its real count (7) rolls up via
        # the await activity instead of being dropped to zero (or recounted as the 1 enumerated id).
        assert result.imported == 7
