from pydantic import BaseModel

MAX_COMPACTION_BATCH_SIZE = 200


class CompactionProgress(BaseModel):
    """Accumulated state carried across continue-as-new executions."""

    cursor: str | None = None
    conversations_compacted: int = 0
    conversations_failed: int = 0
    checkpoints_deleted: int = 0
    blobs_deleted: int = 0


class CompactionSweepInput(BaseModel):
    batch_size: int = 100
    # None flows through to select_compactable_conversation_ids, which resolves the window from
    # CHECKPOINT_COMPACTION_IDLE_DAYS — the single source of truth.
    idle_days: int | None = None
    progress: CompactionProgress | None = None


class SelectBatchInput(BaseModel):
    batch_size: int
    idle_days: int | None = None
    after_id: str | None = None


class CompactionBatch(BaseModel):
    conversation_ids: list[str]


class CompactBatchResult(BaseModel):
    conversations_compacted: int = 0
    conversations_failed: int = 0
    checkpoints_deleted: int = 0
    blobs_deleted: int = 0
