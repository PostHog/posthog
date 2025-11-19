"""Temporal workflow for backfilling materialized property columns."""

from posthog.temporal.backfill_materialized_property.activities import (
    BackfillMaterializedColumnInputs,
    GetSlotDetailsInputs,
    SlotDetails,
    UpdateSlotStateInputs,
    backfill_materialized_column,
    get_slot_details,
    update_slot_state,
)
from posthog.temporal.backfill_materialized_property.workflows import (
    BackfillMaterializedPropertyInputs,
    BackfillMaterializedPropertyWorkflow,
)

ACTIVITIES = [
    get_slot_details,
    backfill_materialized_column,
    update_slot_state,
]

__all__ = [
    "BackfillMaterializedPropertyWorkflow",
    "BackfillMaterializedPropertyInputs",
    "ACTIVITIES",
    "get_slot_details",
    "GetSlotDetailsInputs",
    "SlotDetails",
    "backfill_materialized_column",
    "BackfillMaterializedColumnInputs",
    "update_slot_state",
    "UpdateSlotStateInputs",
]
