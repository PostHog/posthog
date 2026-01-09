"""Temporal workflow for backfilling EAV property tables."""

from posthog.temporal.eav_backfill.activities import (
    BackfillEAVPropertyInputs,
    UpdateEAVSlotStateInputs,
    backfill_eav_property,
    update_eav_slot_state,
)
from posthog.temporal.eav_backfill.workflows import BackfillEAVPropertyWorkflow, BackfillEAVPropertyWorkflowInputs

ACTIVITIES = [
    backfill_eav_property,
    update_eav_slot_state,
]

__all__ = [
    "BackfillEAVPropertyWorkflow",
    "BackfillEAVPropertyWorkflowInputs",
    "ACTIVITIES",
    "backfill_eav_property",
    "BackfillEAVPropertyInputs",
    "update_eav_slot_state",
    "UpdateEAVSlotStateInputs",
]
