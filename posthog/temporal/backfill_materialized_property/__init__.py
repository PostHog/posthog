"""Temporal workflows for backfilling materialized property columns.

Slot allocations go through the weekly batched workflows described in the dynamic property
materialization RFC. Compaction lives in its own workflow so the two paths never share a
transaction or a free-column budget.
"""

from posthog.temporal.backfill_materialized_property.activities import (
    ActivateSlotsInputs,
    AssignCompactionTargetsInputs,
    AssignCompactionTargetsResult,
    AssignPendingColumnsInputs,
    AssignPendingColumnsResult,
    ClearCompactionTargetsInputs,
    FailSlotsInputs,
    FinalizeCompactionInputs,
    PopulateSlotAssignmentsInputs,
    PopulateSlotAssignmentsResult,
    RunBatchedMutationInputs,
    activate_slots,
    assign_compaction_targets,
    assign_pending_columns,
    clear_compaction_targets,
    fail_slots,
    finalize_compaction,
    populate_slot_assignments,
    run_batched_mutation,
)
from posthog.temporal.backfill_materialized_property.workflows import (
    BackfillMaterializedPropertiesBatchInputs,
    BackfillMaterializedPropertiesBatchWorkflow,
    CompactMaterializedColumnsInputs,
    CompactMaterializedColumnsWorkflow,
)

ACTIVITIES = [
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
    "BackfillMaterializedPropertiesBatchWorkflow",
    "BackfillMaterializedPropertiesBatchInputs",
    "CompactMaterializedColumnsWorkflow",
    "CompactMaterializedColumnsInputs",
    "ACTIVITIES",
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
