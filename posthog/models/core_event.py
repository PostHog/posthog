from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class CoreEventCategory(models.TextChoices):
    ACQUISITION = "acquisition", "Acquisition"
    ACTIVATION = "activation", "Activation"
    MONETIZATION = "monetization", "Monetization"
    EXPANSION = "expansion", "Expansion"
    REFERRAL = "referral", "Referral"
    RETENTION = "retention", "Retention"
    CHURN = "churn", "Churn"
    REACTIVATION = "reactivation", "Reactivation"


class CoreEvent(UUIDModel):
    """
    A reusable event definition that can be shared across
    Marketing analytics, Customer analytics, and Revenue analytics.
    """

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="core_events",
    )

    name = models.CharField(
        max_length=255,
        help_text="Display name for this core event",
    )

    description = models.TextField(
        blank=True,
        default="",
        help_text="Optional description",
    )

    category = models.CharField(
        max_length=20,
        choices=CoreEventCategory.choices,
        help_text="Lifecycle category for this core event",
    )

    # Filter configuration stored as JSON - EventsNode, ActionsNode, or DataWarehouseNode
    filter = models.JSONField(
        help_text="Filter configuration - event, action, or data warehouse node",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Core Event"
        verbose_name_plural = "Core Events"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.team_id})"

    def clean(self) -> None:
        """Validate the filter field."""
        super().clean()

        if not self.filter:
            raise ValidationError("Filter configuration is required")

        if not isinstance(self.filter, dict):
            raise ValidationError("Filter must be a dictionary")

        filter_kind = self.filter.get("kind")
        if filter_kind not in ("EventsNode", "ActionsNode", "DataWarehouseNode"):
            raise ValidationError(f"Invalid filter kind: {filter_kind}")

        # Prevent "all events" - EventsNode must have a specific event name
        if filter_kind == "EventsNode":
            event_name = self.filter.get("event")
            if not event_name:
                raise ValidationError("Core event cannot use 'All events'. Please select a specific event.")

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)
