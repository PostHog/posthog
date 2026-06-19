"""Temporal workflow for backfilling materialized property columns.

A single weekly batched workflow fills every PENDING slot in one dict-backed
ALTER TABLE UPDATE per cycle. Per-team slot allocation means slot reuse happens
in place; there is no separate compaction step.
"""

from posthog.temporal.backfill_materialized_property.activities import (
    ActivateSlotsInputs,
    AssignPendingColumnsInputs,
    AssignPendingColumnsResult,
    FailSlotsInputs,
    PopulateSlotAssignmentsInputs,
    PopulateSlotAssignmentsResult,
    RunBatchedMutationInputs,
    activate_slots,
    assign_pending_columns,
    fail_slots,
    populate_slot_assignments,
    run_batched_mutation,
)
from posthog.temporal.backfill_materialized_property.workflows import (
    BackfillMaterializedPropertiesBatchInputs,
    BackfillMaterializedPropertiesBatchWorkflow,
)

ACTIVITIES = [
    assign_pending_columns,
    populate_slot_assignments,
    run_batched_mutation,
    activate_slots,
    fail_slots,
]

__all__ = [
    "BackfillMaterializedPropertiesBatchWorkflow",
    "BackfillMaterializedPropertiesBatchInputs",
    "ACTIVITIES",
    "assign_pending_columns",
    "AssignPendingColumnsInputs",
    "AssignPendingColumnsResult",
    "populate_slot_assignments",
    "PopulateSlotAssignmentsInputs",
    "PopulateSlotAssignmentsResult",
    "run_batched_mutation",
    "RunBatchedMutationInputs",
    "activate_slots",
    "ActivateSlotsInputs",
    "fail_slots",
    "FailSlotsInputs",
]
