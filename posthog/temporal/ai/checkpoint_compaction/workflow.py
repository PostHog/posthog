from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.ai.checkpoint_compaction.activities import (
    compact_checkpoint_conversations,
    select_checkpoint_compaction_batch,
)
from posthog.temporal.ai.checkpoint_compaction.types import (
    CompactBatchResult,
    CompactionBatch,
    CompactionProgress,
    CompactionSweepInput,
    SelectBatchInput,
)
from posthog.temporal.common.base import PostHogWorkflow


@workflow.defn(name="checkpoint-compaction-sweep")
class CheckpointCompactionWorkflow(PostHogWorkflow):
    inputs_cls = CompactionSweepInput
    inputs_optional = True

    @workflow.run
    async def run(self, input: CompactionSweepInput) -> CompactionProgress:
        progress = input.progress or CompactionProgress()

        while True:
            batch: CompactionBatch = await workflow.execute_activity(
                select_checkpoint_compaction_batch,
                SelectBatchInput(
                    batch_size=input.batch_size,
                    idle_days=input.idle_days,
                    after_id=progress.cursor,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                schedule_to_close_timeout=timedelta(minutes=15),
                retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
            )

            if not batch.conversation_ids:
                return progress

            result: CompactBatchResult = await workflow.execute_activity(
                compact_checkpoint_conversations,
                batch,
                start_to_close_timeout=timedelta(minutes=10),
                schedule_to_close_timeout=timedelta(minutes=30),
                retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
            )

            progress.conversations_compacted += result.conversations_compacted
            progress.conversations_failed += result.conversations_failed
            progress.checkpoints_deleted += result.checkpoints_deleted
            progress.blobs_deleted += result.blobs_deleted
            # The selection filter excludes compacted threads, so advancing past the last id we
            # saw also steps over any threads we skipped this run (e.g. pending approval),
            # guaranteeing the cursor always moves forward and the sweep terminates.
            progress.cursor = batch.conversation_ids[-1]

            if workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(
                    CompactionSweepInput(
                        batch_size=input.batch_size,
                        idle_days=input.idle_days,
                        progress=progress,
                    )
                )
