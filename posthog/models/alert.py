from datetime import timedelta, datetime, UTC

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from posthog.models.insight import Insight
from posthog.models.utils import UUIDModel, CreatedMetaFields


def are_alerts_supported_for_insight(insight: Insight) -> bool:
    query = insight.query
    if query is None or query.get("kind") != "TrendsQuery":
        return False
    if query.get("trendsFilter", {}).get("display") != "BoldNumber":
        return False
    return True


class Alert(models.Model):
    """
    @deprecated("AlertConfiguration should be used instead.")
    """

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    insight: models.ForeignKey = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)

    name: models.CharField = models.CharField(max_length=100)
    target_value: models.TextField = models.TextField()
    anomaly_condition: models.JSONField = models.JSONField(default=dict)


class AlertConfiguration(CreatedMetaFields, UUIDModel):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)

    name = models.CharField(max_length=100)
    notification_targets = models.JSONField(default=dict)  # Object with list of emails or other notification targets
    condition = models.JSONField(default=dict)

    STATE_CHOICES = [
        ("firing", "Firing"),
        ("inactive", "Inactive"),
    ]
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="inactive")

    notification_frequency = models.IntegerField(
        default=60,
        help_text="Frequency in minutes",
        validators=[MinValueValidator(60), MaxValueValidator(1440)],
    )
    last_notified_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} (Team: {self.team})"

    def should_send_notification(self):
        """Determine if we should send another notification based on the cooldown period."""
        if not self.last_notified_at:
            return True
        next_allowed_time = self.last_notified_at + timedelta(minutes=self.notification_frequency)
        return datetime.now(UTC) >= next_allowed_time

    def add_check(self, calculated_value, anomaly_condition, error_message=None):
        """Add a new AlertCheck, managing state transitions and cooldown."""
        threshold_met = self.evaluate_condition(calculated_value, anomaly_condition)

        # Determine the appropriate state for this check
        if threshold_met:
            if self.state == "firing" and not self.should_send_notification():
                check_state = "cooldown"
            else:
                check_state = "firing"
                self.last_notified_at = datetime.now(UTC)
        else:
            check_state = "not_met"
            self.state = "inactive"  # Set the Alert to inactive if the threshold is no longer met

        # Create the AlertCheck record
        alert_check = AlertCheck.objects.create(
            alert=self,
            calculated_value=calculated_value,
            anomaly_condition=anomaly_condition,
            threshold_met=threshold_met,
            notification_sent=(check_state == "firing"),
            state=check_state,
            error_message=error_message,
        )

        # Update the Alert state
        if check_state == "firing":
            self.state = "firing"
        elif check_state == "not_met":
            self.state = "inactive"

        self.save()
        return alert_check

    def evaluate_condition(self, calculated_value, anomaly_condition):
        """Placeholder method to evaluate if the condition is met."""
        # Implement actual condition evaluation logic here
        return calculated_value > anomaly_condition.get("threshold", 0)


class AlertCheck(UUIDModel):
    alert_configuration = models.ForeignKey(AlertConfiguration, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    calculated_value = models.FloatField(null=True, blank=True)
    condition = models.JSONField(default=dict)  # Snapshot of the condition at the time of the check
    targets_notified = models.JSONField(default=dict)
    error_message = models.TextField(null=True, blank=True)

    STATE_CHOICES = [
        ("firing", "Firing"),
        ("cooldown", "Cooldown"),
        ("not_met", "Not Met"),
    ]
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="not_met")

    def __str__(self):
        return f"AlertCheck for {self.alert_configuration.name} at {self.created_at}"
