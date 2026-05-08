from django.db import models

from posthog.models.team import Team
from posthog.models.utils import UUIDTModel

from products.event_definitions.backend.models import PropertyDefinition

MAX_SLOTS_PER_TEAM = 5

# Inclusive — must stay paired with `DMAT_STRING_COLUMN_COUNT` in posthog/models/event/sql.py.
MAX_SLOT_INDEX = 99

# Compaction and PENDING allocation each consume up to MAX_SLOTS_PER_TEAM columns from the
# global free pool, so the threshold is set to 2 * MAX_SLOTS_PER_TEAM — guarantees compaction
# always has headroom to allocate dense targets even after a full PENDING week.
COMPACTION_FREE_COLUMN_THRESHOLD = 10


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
    # Set during compaction — the slot is being repacked into a smaller column index so the old
    # one can be freed. While this is set, ingestion writes to BOTH columns (slot_index AND
    # compaction_target_slot_index) so HogQL reads stay correct on the old column until the
    # weekly mutation finishes backfilling the new column. After the mutation completes, the
    # workflow swaps slot_index ← compaction_target_slot_index and clears this field.
    compaction_target_slot_index = models.PositiveSmallIntegerField(null=True, blank=True)
    state = models.CharField(
        max_length=20,
        choices=MaterializedColumnSlotState,
        default=MaterializedColumnSlotState.PENDING,
    )
    # Temporal run_id of the workflow execution that owns this slot's current BACKFILL transition.
    # The weekly schedule reuses one workflow_id, so run_id (unique per execution, stable across
    # activity retries) is what the assign activity uses for idempotency and stranded-slot detection.
    # `db_column` keeps the existing physical column name; renaming columns in prod is unsafe
    # (see safe-django-migrations.md), so the Python attribute is renamed but the DB column
    # remains `backfill_temporal_workflow_id`.
    backfill_temporal_run_id = models.CharField(
        max_length=400,
        db_column="backfill_temporal_workflow_id",
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
            # are shared across teams (one column physically; per-row team_id discriminates
            # via the multiIf branches in the backfill mutation), but within a team each
            # slot must own a distinct index so dual-writes don't collide.
            models.UniqueConstraint(
                fields=["team", "slot_index"],
                name="unique_team_slot_index",
                condition=models.Q(slot_index__isnull=False),
            ),
            # Defense-in-depth — the planner enforces this in code; the constraint catches
            # hand edits and any future planner regression that would otherwise let two slots
            # in one team dual-write to the same target column.
            models.UniqueConstraint(
                fields=["team", "compaction_target_slot_index"],
                name="unique_team_compaction_target",
                condition=models.Q(compaction_target_slot_index__isnull=False),
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
            models.CheckConstraint(
                name="valid_compaction_target_slot_index",
                condition=models.Q(compaction_target_slot_index__isnull=True)
                | (
                    models.Q(compaction_target_slot_index__gte=0)
                    & models.Q(compaction_target_slot_index__lte=MAX_SLOT_INDEX)
                ),
            ),
        ]
        indexes = [
            models.Index(fields=["team", "state"], name="posthog_mat_team_st_idx"),
            models.Index(fields=["team", "property_definition"], name="posthog_mat_team_pr_idx"),
            models.Index(fields=["team", "slot_index"], name="posthog_mat_team_sl_idx"),
            # Index name mirrors the legacy DB column (`backfill_temporal_workflow_id`); the
            # Python attribute was renamed via db_column on the field, the physical column
            # and its index didn't move.
            models.Index(fields=["backfill_temporal_run_id"], name="posthog_mat_backfi_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.property_definition.name} -> slot {self.slot_index} ({self.state})"
