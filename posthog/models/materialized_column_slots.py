from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver

from posthog.models.team import Team
from posthog.models.utils import UUIDTModel

from products.event_definitions.backend.models import PropertyDefinition, PropertyType

# Maximum number of materialized column slots a team can hold across all states.
# Per the dynamic property materialization RFC: balances utility vs column consumption.
MAX_SLOTS_PER_TEAM = 5

# Maximum slot_index value (inclusive). 100 string columns are pre-allocated in ClickHouse,
# numbered 0..99 — see DMAT_STRING_COLUMN_COUNT in posthog/models/event/sql.py.
MAX_SLOT_INDEX = 99

# Compaction triggers when fewer than this many free string columns remain across all teams.
# Picked to match a single weekly cycle's worst-case demand: every onboarded team uses up to
# MAX_SLOTS_PER_TEAM columns. Below the threshold the workflow re-packs all existing
# assignments into a small dense range, freeing the rest for the next ~19 weeks.
COMPACTION_FREE_COLUMN_THRESHOLD = 5


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
    # Denormalized from PropertyDefinition for efficient constraints and queries
    property_type = models.CharField(max_length=50, choices=PropertyType)
    # Null while in PENDING — assigned by the weekly backfill workflow when the slot transitions
    # to BACKFILL. The unique constraint on (team, property_type, slot_index) only applies to rows
    # with a non-null slot_index, so multiple PENDING slots can coexist without conflict.
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
    backfill_temporal_workflow_id = models.CharField(max_length=400, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "property_definition"],
                name="unique_team_property_definition",
            ),
            models.UniqueConstraint(
                fields=["team", "property_type", "slot_index"],
                name="unique_team_property_type_slot_index",
                condition=models.Q(slot_index__isnull=False),
            ),
            # Mirrors the slot_index uniqueness for compaction_target_slot_index. The planner
            # already enforces per-team uniqueness in code; this is the safety net for hand
            # edits, manual recovery, and any future planner regression — without it, two
            # slots in one team could end up dual-writing to the same target column and
            # silently corrupting each other's values.
            models.UniqueConstraint(
                fields=["team", "property_type", "compaction_target_slot_index"],
                name="unique_team_property_type_compaction_target",
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
            models.Index(fields=["team", "property_type", "slot_index"], name="posthog_mat_team_ty_idx"),
            models.Index(fields=["backfill_temporal_workflow_id"], name="posthog_mat_backfi_idx"),
        ]

    def save(self, *args, **kwargs):
        # Sync property_type from property_definition on save
        if self.property_definition_id and not self.property_type:
            self.property_type = self.property_definition.property_type  # type: ignore[assignment]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.property_definition.name} ({self.property_type}) -> slot {self.slot_index} ({self.state})"


@receiver(pre_save, sender=PropertyDefinition)
def prevent_property_type_changes_with_materialized_slots(sender, instance, **kwargs):
    """
    Prevent changing property_type on a PropertyDefinition if it has any
    MaterializedColumnSlot records, since the property_type is part of the
    slot allocation constraint.
    """
    if instance.pk:  # Only for updates, not creates
        try:
            old_instance = PropertyDefinition.objects.get(pk=instance.pk)
            if old_instance.property_type != instance.property_type:
                # Check if this property has any materialized slots
                if MaterializedColumnSlot.objects.filter(property_definition=instance).exists():
                    raise ValidationError(
                        f"Cannot change property_type for '{instance.name}' because it has materialized column slots. "
                        "Delete the materialized slots first."
                    )
        except PropertyDefinition.DoesNotExist:
            pass
