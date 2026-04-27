"""Temporal workflows for backfilling materialized property columns.

The legacy per-slot workflow remains registered for in-flight backfills, but new slot
allocations go through the weekly batched workflow described in the dynamic property
materialization RFC.
"""

from posthog.temporal.backfill_materialized_property.activities import (
    ActivateSlotsInputs,
    AssignPendingSlotsInputs,
    AssignPendingSlotsResult,
    BackfillMaterializedColumnInputs,
    ClearCompactionTargetsInputs,
    FailSlotsInputs,
    FinalizeCompactionInputs,
    RunBatchedMutationInputs,
    UpdateSlotStateInputs,
    activate_slots,
    assign_pending_slots,
    backfill_materialized_column,
    clear_compaction_targets,
    fail_slots,
    finalize_compaction,
    run_batched_mutation,
    update_slot_state,
)
from posthog.temporal.backfill_materialized_property.workflows import (
    BackfillMaterializedPropertiesBatchInputs,
    BackfillMaterializedPropertiesBatchWorkflow,
    BackfillMaterializedPropertyInputs,
    BackfillMaterializedPropertyWorkflow,
)

ACTIVITIES = [
    backfill_materialized_column,
    update_slot_state,
    assign_pending_slots,
    run_batched_mutation,
    activate_slots,
    fail_slots,
    finalize_compaction,
    clear_compaction_targets,
]

__all__ = [
    "BackfillMaterializedPropertyWorkflow",
    "BackfillMaterializedPropertyInputs",
    "BackfillMaterializedPropertiesBatchWorkflow",
    "BackfillMaterializedPropertiesBatchInputs",
    "ACTIVITIES",
    "backfill_materialized_column",
    "BackfillMaterializedColumnInputs",
    "update_slot_state",
    "UpdateSlotStateInputs",
    "assign_pending_slots",
    "AssignPendingSlotsInputs",
    "AssignPendingSlotsResult",
    "run_batched_mutation",
    "RunBatchedMutationInputs",
    "activate_slots",
    "ActivateSlotsInputs",
    "fail_slots",
    "FailSlotsInputs",
    "finalize_compaction",
    "FinalizeCompactionInputs",
    "clear_compaction_targets",
    "ClearCompactionTargetsInputs",
]
