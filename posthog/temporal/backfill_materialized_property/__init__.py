"""Temporal workflow for backfilling materialized property columns."""

from posthog.temporal.backfill_materialized_property.activities import (
    BackfillMaterializedColumnInputs,
    UpdateSlotStateInputs,
    backfill_materialized_column,
    update_slot_state,
)
from posthog.temporal.backfill_materialized_property.workflows import (
    BackfillMaterializedPropertyInputs,
    BackfillMaterializedPropertyWorkflow,
)

ACTIVITIES = [
    backfill_materialized_column,
    update_slot_state,
]

__all__ = [
    "BackfillMaterializedPropertyWorkflow",
    "BackfillMaterializedPropertyInputs",
    "ACTIVITIES",
    "backfill_materialized_column",
    "BackfillMaterializedColumnInputs",
    "update_slot_state",
    "UpdateSlotStateInputs",
]
