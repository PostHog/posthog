from __future__ import annotations

import pytest

from django.conf import settings

from temporalio import activity, workflow

from products.conversations.backend.temporal.zendesk_import.activities import (
    EnumerateTicketsInput,
    EnumerateTicketsOutput,
    UpdateJobProgressInput,
    UpdateJobStatusInput,
)
from products.conversations.backend.temporal.zendesk_import.constants import CONTINUE_AS_NEW_AFTER_PAGES
from products.conversations.backend.temporal.zendesk_import.workflows import (
    ZendeskImportBatchWorkflowInput,
    ZendeskImportCoordinatorInput,
    ZendeskImportCoordinatorOutput,
    ZendeskImportCoordinatorWorkflow,
)

# Enough pages to cross exactly one continue-as-new boundary: the first generation processes
# CONTINUE_AS_NEW_AFTER_PAGES pages, the second processes the remainder. One unique ticket per
# page, so a fully-successful import returns exactly TOTAL_PAGES imported.
TOTAL_PAGES = CONTINUE_AS_NEW_AFTER_PAGES + 5


def _page_from_cursor(cursor: str | None) -> int:
    return 0 if cursor is None else int(cursor)


@activity.defn(name="zendesk_import_enumerate_tickets_activity")
async def _fake_enumerate(input: EnumerateTicketsInput) -> EnumerateTicketsOutput:
    page = _page_from_cursor(input.cursor)
    return EnumerateTicketsOutput(
        ticket_ids=[1000 + page],
        next_cursor=str(page + 1),
        end_of_stream=(page + 1 >= TOTAL_PAGES),
    )


@activity.defn(name="zendesk_import_update_job_progress_activity")
async def _fake_progress(input: UpdateJobProgressInput) -> None:
    return None


@activity.defn(name="zendesk_import_update_job_status_activity")
async def _fake_status(input: UpdateJobStatusInput) -> None:
    return None


@workflow.defn(name="zendesk-import-batch")
class _StubBatchWorkflow:
    """Stands in for ZendeskImportBatchWorkflow (same registered name). Reports one import per
    ticket id it actually receives, so a batch that never runs (child-id collision -> the
    coordinator swallows WorkflowAlreadyStartedError and returns zeros) contributes nothing to the
    total — that's the signal this test keys on."""

    @workflow.run
    async def run(self, input: ZendeskImportBatchWorkflowInput) -> ZendeskImportCoordinatorOutput:
        return ZendeskImportCoordinatorOutput(imported=len(input.ticket_ids), skipped=0, failed=0)


class TestZendeskImportCoordinatorContinueAsNew:
    @pytest.mark.asyncio
    async def test_import_continues_past_continue_as_new_boundary(self) -> None:
        # Regression: child workflow ids must stay globally unique across continue-as-new. If they
        # revert to the per-generation pages_processed (which resets to 0 each generation), the
        # second generation regenerates the first generation's completed child ids; with
        # ALLOW_DUPLICATE_FAILED_ONLY every such start raises WorkflowAlreadyStartedError, the
        # coordinator counts zero, and the import silently stalls at the boundary (~50k tickets).
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        # Children are dispatched to this queue explicitly, so the worker must host it (single queue
        # for coordinator + children keeps the test self-contained).
        task_queue = settings.VIDEO_EXPORT_TASK_QUEUE

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[ZendeskImportCoordinatorWorkflow, _StubBatchWorkflow],
                activities=[_fake_enumerate, _fake_progress, _fake_status],
            ):
                result = await env.client.execute_workflow(
                    ZendeskImportCoordinatorWorkflow.run,
                    ZendeskImportCoordinatorInput(job_id="job-1", team_id=1),
                    id="test-zendesk-import-can",
                    task_queue=task_queue,
                )

        # Every enumerated ticket imported — nothing lost at the continue-as-new boundary.
        assert result.imported == TOTAL_PAGES
