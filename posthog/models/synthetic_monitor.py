from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.utils import CreatedMetaFields, UUIDTModel


class SyntheticMonitor(CreatedMetaFields, UUIDTModel):
    """
    Configuration for synthetic HTTP monitoring checks (uptime and latency).
    All check results are stored as events in ClickHouse. Monitor state (last_checked_at,
    consecutive_failures, state) is computed from ClickHouse events on-demand.
    """

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400)

    # Check configuration
    url = models.URLField()
    frequency_minutes = models.IntegerField(
        choices=[(1, "1 minute"), (5, "5 minutes"), (15, "15 minutes"), (30, "30 minutes"), (60, "60 minutes")]
    )
    regions = models.JSONField(
        default=list, help_text="List of regions to run checks from (e.g., ['us-east-1', 'eu-west-1'])"
    )

    # HTTP configuration
    method = models.CharField(max_length=10, default="GET")
    headers = models.JSONField(
        null=True, blank=True, help_text="Custom HTTP headers as JSON object (e.g., {'Authorization': 'Bearer ...'})"
    )
    body = models.TextField(null=True, blank=True, help_text="Request body for POST/PUT requests")
    expected_status_code = models.IntegerField(default=200)
    timeout_seconds = models.IntegerField(default=30)

    # Alert configuration (integrated, not separate AlertConfiguration)
    alert_enabled = models.BooleanField(default=True)
    alert_threshold_failures = models.IntegerField(
        default=3, help_text="Number of consecutive failures before triggering an alert"
    )
    alert_recipients = models.ManyToManyField(
        "User",
        blank=True,
        related_name="synthetic_monitors",
        help_text="Users to notify when alerts trigger",
    )
    slack_integration = models.ForeignKey(
        "Integration",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Slack integration for alert notifications",
    )

    # Monitor state
    enabled = models.BooleanField(default=True)
    last_alerted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "enabled"]),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.method not in ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]:
            raise ValidationError({"method": "Invalid HTTP method"})

        if self.expected_status_code < 100 or self.expected_status_code >= 600:
            raise ValidationError({"expected_status_code": "Status code must be between 100 and 599"})

        if self.regions and not isinstance(self.regions, list):
            raise ValidationError({"regions": "Regions must be a list"})
