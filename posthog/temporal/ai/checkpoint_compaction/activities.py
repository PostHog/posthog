from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.ai.checkpoint_compaction.types import (
    MAX_COMPACTION_BATCH_SIZE,
    CompactBatchResult,
    CompactionBatch,
    SelectBatchInput,
)
from posthog.temporal.common.logger import get_write_only_logger

from ee.hogai.django_checkpoint.compaction import compact_thread, select_compactable_conversation_ids

LOGGER = get_write_only_logger()


@activity.defn(name="select-checkpoint-compaction-batch")
async def select_checkpoint_compaction_batch(input: SelectBatchInput) -> CompactionBatch:
    limit = min(input.batch_size, MAX_COMPACTION_BATCH_SIZE)
    conversation_ids = await database_sync_to_async(select_compactable_conversation_ids, thread_sensitive=False)(
        limit=limit, after_id=input.after_id, idle_days=input.idle_days
    )
    ids = [str(conversation_id) for conversation_id in conversation_ids]
    LOGGER.bind().info("Selected checkpoint compaction batch", count=len(ids), after_id=input.after_id)
    return CompactionBatch(conversation_ids=ids)


@activity.defn(name="compact-checkpoint-conversations")
async def compact_checkpoint_conversations(input: CompactionBatch) -> CompactBatchResult:
    def _compact() -> CompactBatchResult:
        conversations_compacted = 0
        conversations_failed = 0
        checkpoints_deleted = 0
        blobs_deleted = 0
        for conversation_id in input.conversation_ids:
            try:
                outcome = compact_thread(conversation_id)
            except Exception:
                # One poison thread must not sink the whole batch (and with it the daily sweep).
                conversations_failed += 1
                LOGGER.bind().exception("Checkpoint compaction failed", conversation_id=conversation_id)
                continue
            if outcome.compacted:
                conversations_compacted += 1
                checkpoints_deleted += outcome.checkpoints_deleted
                blobs_deleted += outcome.blobs_deleted
        return CompactBatchResult(
            conversations_compacted=conversations_compacted,
            conversations_failed=conversations_failed,
            checkpoints_deleted=checkpoints_deleted,
            blobs_deleted=blobs_deleted,
        )

    result = await database_sync_to_async(_compact, thread_sensitive=False)()
    LOGGER.bind().info(
        "Compacted checkpoint conversations",
        requested=len(input.conversation_ids),
        compacted=result.conversations_compacted,
        failed=result.conversations_failed,
        checkpoints_deleted=result.checkpoints_deleted,
        blobs_deleted=result.blobs_deleted,
    )
    return result
