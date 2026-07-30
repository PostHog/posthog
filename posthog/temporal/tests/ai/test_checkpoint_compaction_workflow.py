import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.ai.checkpoint_compaction.types import (
    CompactBatchResult,
    CompactionBatch,
    CompactionProgress,
    CompactionSweepInput,
    SelectBatchInput,
)
from posthog.temporal.ai.checkpoint_compaction.workflow import CheckpointCompactionWorkflow


async def _run_with_activities(select_activity, compact_activity, sweep_input: CompactionSweepInput):
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[CheckpointCompactionWorkflow],
            activities=[select_activity, compact_activity],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                CheckpointCompactionWorkflow.run,
                sweep_input,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
    return CompactionProgress.model_validate(result)


@pytest.mark.asyncio
async def test_sweep_drains_every_page_and_aggregates_totals():
    pages: dict[str | None, list[str]] = {None: ["a", "b"], "b": ["c"], "c": []}
    compacted_batches: list[list[str]] = []

    @activity.defn(name="select-checkpoint-compaction-batch")
    async def select_mocked(input: SelectBatchInput) -> CompactionBatch:
        return CompactionBatch(conversation_ids=pages[input.after_id])

    @activity.defn(name="compact-checkpoint-conversations")
    async def compact_mocked(input: CompactionBatch) -> CompactBatchResult:
        compacted_batches.append(list(input.conversation_ids))
        n = len(input.conversation_ids)
        return CompactBatchResult(conversations_compacted=n, checkpoints_deleted=2 * n, blobs_deleted=3 * n)

    progress = await _run_with_activities(select_mocked, compact_mocked, CompactionSweepInput(batch_size=2))

    # Cursor follows the last id of each page, so pages are visited in order and the sweep stops
    # once an empty page comes back.
    assert compacted_batches == [["a", "b"], ["c"]]
    assert progress.conversations_compacted == 3
    assert progress.checkpoints_deleted == 6
    assert progress.blobs_deleted == 9
    assert progress.cursor == "c"


@pytest.mark.asyncio
async def test_sweep_with_nothing_to_compact_is_a_noop():
    @activity.defn(name="select-checkpoint-compaction-batch")
    async def select_empty(input: SelectBatchInput) -> CompactionBatch:
        return CompactionBatch(conversation_ids=[])

    @activity.defn(name="compact-checkpoint-conversations")
    async def compact_never(input: CompactionBatch) -> CompactBatchResult:
        raise AssertionError("compaction should not run when there is nothing to compact")

    progress = await _run_with_activities(select_empty, compact_never, CompactionSweepInput())

    assert progress.conversations_compacted == 0
    assert progress.cursor is None
