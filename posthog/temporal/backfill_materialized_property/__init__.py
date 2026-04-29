"""Temporal workflows for backfilling materialized property columns.

The legacy per-slot workflow remains registered for in-flight backfills, but new slot
allocations go through the weekly batched workflows described in the dynamic property
materialization RFC. Compaction lives in its own workflow so the two paths never share
a transaction or a free-column budget.
"""

from posthog.temporal.backfill_materialized_property.activities import (
    ActivateSlotsInputs,
    AssignCompactionTargetsInputs,
    AssignCompactionTargetsResult,
    AssignPendingColumnsInputs,
    AssignPendingColumnsResult,
    BackfillMaterializedColumnInputs,
    ClearCompactionTargetsInputs,
    FailSlotsInputs,
    FinalizeCompactionInputs,
    PopulateSlotAssignmentsInputs,
    PopulateSlotAssignmentsResult,
    RunBatchedMutationInputs,
    UpdateSlotStateInputs,
    activate_slots,
    assign_compaction_targets,
    assign_pending_columns,
    backfill_materialized_column,
    clear_compaction_targets,
    fail_slots,
    finalize_compaction,
    populate_slot_assignments,
    run_batched_mutation,
    update_slot_state,
)
from posthog.temporal.backfill_materialized_property.workflows import (
    BackfillMaterializedPropertiesBatchInputs,
    BackfillMaterializedPropertiesBatchWorkflow,
    BackfillMaterializedPropertyInputs,
    BackfillMaterializedPropertyWorkflow,
    CompactMaterializedColumnsInputs,
    CompactMaterializedColumnsWorkflow,
)

ACTIVITIES = [
    backfill_materialized_column,
    update_slot_state,
    assign_pending_columns,
    assign_compaction_targets,
    populate_slot_assignments,
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
    "CompactMaterializedColumnsWorkflow",
    "CompactMaterializedColumnsInputs",
    "ACTIVITIES",
    "backfill_materialized_column",
    "BackfillMaterializedColumnInputs",
    "update_slot_state",
    "UpdateSlotStateInputs",
    "assign_pending_columns",
    "AssignPendingColumnsInputs",
    "AssignPendingColumnsResult",
    "assign_compaction_targets",
    "AssignCompactionTargetsInputs",
    "AssignCompactionTargetsResult",
    "populate_slot_assignments",
    "PopulateSlotAssignmentsInputs",
    "PopulateSlotAssignmentsResult",
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
