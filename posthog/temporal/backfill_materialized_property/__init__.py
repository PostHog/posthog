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

# Plugin-server TeamManager cache TTL in seconds
# IMPORTANT: Must match plugin-server/src/utils/team-manager.ts refreshAgeMs (2 * 60 * 1000 ms)
# The workflow waits this long to ensure ingestion cache refreshes before backfill starts
PLUGIN_SERVER_TEAM_CACHE_TTL_SECONDS = 120

ACTIVITIES = [
    get_slot_details,
    backfill_materialized_column,
    update_slot_state,
]

__all__ = [
    "BackfillMaterializedPropertyWorkflow",
    "BackfillMaterializedPropertyInputs",
    "ACTIVITIES",
    "PLUGIN_SERVER_TEAM_CACHE_TTL_SECONDS",
    "get_slot_details",
    "GetSlotDetailsInputs",
    "SlotDetails",
    "backfill_materialized_column",
    "BackfillMaterializedColumnInputs",
    "update_slot_state",
    "UpdateSlotStateInputs",
]
