from django.db import models

from posthog.models.property_definition import PropertyType
from posthog.models.team import Team
from posthog.models.utils import UUIDTModel


class MaterializedColumnSlotState(models.TextChoices):
    BACKFILL = "BACKFILL", "Backfill"
    READY = "READY", "Ready"
    ERROR = "ERROR", "Error"


class MaterializationType(models.TextChoices):
    DMAT = "dmat", "Dynamic Materialized Column"
    EAV = "eav", "EAV Table"


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
    property_name = models.CharField(max_length=400)
    property_type = models.CharField(max_length=50, choices=PropertyType.choices)
    slot_index = models.PositiveSmallIntegerField()
    state = models.CharField(
        max_length=20,
        choices=MaterializedColumnSlotState.choices,
        default=MaterializedColumnSlotState.BACKFILL,
    )
    backfill_temporal_workflow_id = models.CharField(max_length=400, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    materialization_type = models.CharField(
        max_length=10,
        choices=MaterializationType.choices,
        default=MaterializationType.DMAT,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "property_name"],
                name="unique_team_property_name",
            ),
            # DMAT slots need unique (team, property_type, slot_index) to manage the 10 slots per type
            # EAV slots don't use slot_index so they're excluded from this constraint
            models.UniqueConstraint(
                fields=["team", "property_type", "slot_index"],
                name="unique_team_property_type_slot_index_dmat",
                condition=models.Q(materialization_type="dmat"),
            ),
            # DMAT slots must have slot_index between 0-9, EAV slots always use 0 (unused)
            models.CheckConstraint(
                name="valid_slot_index_dmat",
                check=models.Q(materialization_type="eav")
                | (models.Q(slot_index__gte=0) & models.Q(slot_index__lte=9)),
            ),
        ]
        indexes = [
            models.Index(fields=["team", "state"], name="posthog_mat_team_st_idx"),
            models.Index(fields=["team", "property_name"], name="posthog_mat_team_pr_idx"),
            models.Index(fields=["team", "property_type", "slot_index"], name="posthog_mat_team_ty_idx"),
            models.Index(fields=["backfill_temporal_workflow_id"], name="posthog_mat_backfi_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.property_name} ({self.property_type}) -> slot {self.slot_index} ({self.state})"
