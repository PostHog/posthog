from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel


class AITokenMeteringState(CreatedMetaFields, UUIDModel):
    """
    Tracks the state of AI token metering for each team with Stripe integration.

    This model keeps track of:
    - When Stripe was enabled for the team
    - The last timestamp that was successfully processed
    - Whether the workflow is currently active
    - The temporal workflow ID for management
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="ai_token_metering_states")

    # When Stripe integration was enabled - this is our starting point for processing
    stripe_enabled_at = models.DateTimeField(
        help_text="Timestamp when Stripe integration was enabled. Processing starts from this time."
    )

    # Last timestamp that was successfully processed and sent to Stripe
    last_processed_timestamp = models.DateTimeField(
        help_text="The end timestamp of the last successfully processed time range"
    )

    # For tracking the current processing window (helps with recovery/debugging)
    current_processing_start = models.DateTimeField(
        null=True, blank=True, help_text="Start timestamp of the currently processing time range"
    )

    # Temporal workflow ID for this team's metering workflow
    workflow_id = models.CharField(
        max_length=255, null=True, blank=True, help_text="Temporal workflow ID for managing this team's metering"
    )

    # Whether this metering state is active (Stripe is currently enabled)
    is_active = models.BooleanField(
        default=True, help_text="Whether the Stripe integration is currently active for this team"
    )

    class Meta:
        indexes = [
            models.Index(fields=["team", "is_active"]),
            models.Index(fields=["is_active", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"AITokenMeteringState(team={self.team_id}, active={self.is_active}, last_processed={self.last_processed_timestamp})"
