from django.db import models

from posthog.models.event.sql import DMAT_STRING_COLUMN_COUNT
from posthog.models.team import Team
from posthog.models.utils import UUIDTModel

from products.event_definitions.backend.models import PropertyDefinition

# Single source of truth is the physical dmat_string pool size in event/sql.py. Per-team
# cap equals pool size because slots are allocated per-team and indices are shared across
# teams (the dmat dict resolves (team_id, slot_index) -> property_name at write/read time).
MAX_SLOTS_PER_TEAM = DMAT_STRING_COLUMN_COUNT
MAX_SLOT_INDEX = MAX_SLOTS_PER_TEAM - 1


class MaterializedColumnSlotState(models.TextChoices):
    # PENDING: queued for the next weekly backfill cycle. No ingestion writes, no query reads.
    PENDING = "PENDING", "Pending"
    # BACKFILL: assigned a slot_index; ingestion writes new events but historical backfill is in flight.
    # Query reads still use JSON until READY to avoid serving partial data.
    BACKFILL = "BACKFILL", "Backfill"
    # READY: backfill complete; HogQL serves reads from the dmat column.
    READY = "READY", "Ready"
    # ERROR: backfill failed; can be retried by transitioning back to PENDING.
    ERROR = "ERROR", "Error"


class MaterializedColumnSlot(UUIDTModel):
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="materialized_column_slots",
        related_query_name="materialized_column_slot",
    )
    property_definition = models.ForeignKey(
        PropertyDefinition,
        on_delete=models.CASCADE,
        related_name="materialized_column_slots",
        related_query_name="materialized_column_slot",
    )
    # Null while in PENDING — assigned by the weekly backfill workflow when the slot transitions
    # to BACKFILL. The unique constraint on (team, slot_index) only applies to rows with a
    # non-null slot_index, so multiple PENDING slots can coexist without conflict.
    slot_index = models.PositiveSmallIntegerField(null=True, blank=True)
    state = models.CharField(
        max_length=20,
        choices=MaterializedColumnSlotState,
        default=MaterializedColumnSlotState.PENDING,
    )
    # Temporal run_id of the workflow execution that owns this slot's current BACKFILL transition.
    # The weekly schedule reuses one workflow_id, so run_id (unique per execution, stable across
    # activity retries) is what the assign activity uses for idempotency and stranded-slot detection.
    backfill_temporal_run_id = models.CharField(
        max_length=400,
        null=True,
        blank=True,
    )
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "property_definition"],
                name="unique_team_property_definition",
            ),
            # Per-team uniqueness on the assigned column index. The dmat_string_<idx> columns
            # are shared across teams (one column physically; the dmat dict resolves
            # (team_id, slot_index) → property_name per row), but within a team each slot
            # must own a distinct index.
            models.UniqueConstraint(
                fields=["team", "slot_index"],
                name="unique_team_slot_index",
                condition=models.Q(slot_index__isnull=False),
            ),
            models.CheckConstraint(
                name="valid_slot_index",
                condition=models.Q(slot_index__isnull=True)
                | (models.Q(slot_index__gte=0) & models.Q(slot_index__lte=MAX_SLOT_INDEX)),
            ),
            models.CheckConstraint(
                name="slot_index_required_when_assigned",
                condition=(
                    models.Q(state=MaterializedColumnSlotState.PENDING)
                    | models.Q(state=MaterializedColumnSlotState.ERROR)
                    | models.Q(slot_index__isnull=False)
                ),
            ),
        ]
        indexes = [
            models.Index(fields=["team", "state"], name="posthog_mat_team_st_idx"),
            models.Index(fields=["team", "property_definition"], name="posthog_mat_team_pr_idx"),
            models.Index(fields=["team", "slot_index"], name="posthog_mat_team_sl_idx"),
            models.Index(fields=["backfill_temporal_run_id"], name="posthog_mat_run_id_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.property_definition.name} -> slot {self.slot_index} ({self.state})"
