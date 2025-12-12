from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver

from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.models.team import Team
from posthog.models.utils import UUIDTModel


class MaterializedColumnSlotState(models.TextChoices):
    BACKFILL = "BACKFILL", "Backfill"
    READY = "READY", "Ready"
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
    property_type = models.CharField(max_length=50, choices=PropertyType.choices)
    slot_index = models.PositiveSmallIntegerField()
    state = models.CharField(
        max_length=20,
        choices=MaterializedColumnSlotState.choices,
        default=MaterializedColumnSlotState.BACKFILL,
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
            ),
            models.CheckConstraint(
                name="valid_slot_index",
                check=models.Q(slot_index__gte=0) & models.Q(slot_index__lte=9),
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
