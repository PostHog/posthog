from posthog.temporal.ai.checkpoint_compaction.activities import (
    compact_checkpoint_conversations,
    select_checkpoint_compaction_batch,
)
from posthog.temporal.ai.checkpoint_compaction.workflow import CheckpointCompactionWorkflow

CHECKPOINT_COMPACTION_WORKFLOWS = [CheckpointCompactionWorkflow]
CHECKPOINT_COMPACTION_ACTIVITIES = [select_checkpoint_compaction_batch, compact_checkpoint_conversations]
