from datetime import UTC, datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.utils import CreatedMetaFields, UUIDTModel


class SyntheticMonitor(CreatedMetaFields, UUIDTModel):
    """
    Configuration for synthetic HTTP monitoring checks (uptime and latency).
    Each monitor runs periodically and emits events to PostHog for analytics.
    Check results are stored as events in ClickHouse, not in a separate table.
    """

    class MonitorState(models.TextChoices):
        HEALTHY = "healthy", "Healthy"
        FAILING = "failing", "Failing"
        ERROR = "error", "Error"
        DISABLED = "disabled", "Disabled"

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
    state = models.CharField(max_length=20, choices=MonitorState.choices, default=MonitorState.HEALTHY)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.IntegerField(default=0)
    last_alerted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(frequency_minutes__in=[1, 5, 15, 30, 60]),
                name="valid_frequency_minutes",
            )
        ]
        indexes = [
            models.Index(fields=["team", "enabled"]),
            models.Index(fields=["next_check_at"]),
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

    def calculate_next_check_at(self) -> datetime:
        """Calculate when the next check should run based on frequency"""
        now = datetime.now(UTC)
        return now + timedelta(minutes=self.frequency_minutes)

    def update_next_check(self):
        """Update next_check_at field"""
        self.next_check_at = self.calculate_next_check_at()

    def record_success(self):
        """Record a successful check"""
        self.consecutive_failures = 0
        if self.state == self.MonitorState.FAILING:
            self.state = self.MonitorState.HEALTHY
        self.last_checked_at = datetime.now(UTC)
        self.update_next_check()

    def record_failure(self):
        """Record a failed check and update state"""
        self.consecutive_failures += 1
        self.last_checked_at = datetime.now(UTC)

        if self.alert_enabled and self.consecutive_failures >= self.alert_threshold_failures:
            if self.state != self.MonitorState.FAILING:
                self.state = self.MonitorState.FAILING
        self.update_next_check()

    def should_trigger_alert(self) -> bool:
        """Check if an alert should be triggered"""
        if not self.alert_enabled:
            return False

        if self.consecutive_failures < self.alert_threshold_failures:
            return False

        if self.consecutive_failures == self.alert_threshold_failures:
            return True

        return False
