from datetime import datetime, UTC
from typing import Any

from django.db import models
from posthog.models.insight import Insight
from posthog.models.utils import UUIDModel, CreatedMetaFields
from posthog.schema import AlertCondition


def are_alerts_supported_for_insight(insight: Insight) -> bool:
    query = insight.query
    if query is None or query.get("kind") != "TrendsQuery":
        return False
    if query.get("trendsFilter", {}).get("display") != "BoldNumber":
        return False
    return True


class ConditionValidator:
    def __init__(self, condition: AlertCondition):
        self.condition = condition

    def validate(self, calculated_value: float) -> list[str]:
        validators: Any = [
            self.validate_absolute_threshold,
        ]
        matches = []
        for validator in validators:
            matches += validator(calculated_value)
        return matches

    def validate_absolute_threshold(self, calculated_value: float) -> list[str]:
        thresholds = self.condition.absoluteThreshold
        if thresholds.lower is not None and calculated_value < thresholds.lower:
            return [f"The trend value ({calculated_value}) is below the lower threshold ({thresholds.lower})"]
        if thresholds.upper is not None and calculated_value > thresholds.upper:
            return [f"The trend value ({calculated_value}) is above the upper threshold ({thresholds.upper})"]
        return []


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
    enabled = models.BooleanField(default=True)

    last_notified_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} (Team: {self.team})"

    def evaluate_condition(self, calculated_value) -> list[str]:
        condition = AlertCondition.model_validate(self.condition)
        validator = ConditionValidator(condition)
        return validator.validate(calculated_value)

    def add_check(self, calculated_value, error_message=None) -> ["AlertCheck", list[str]]:
        """Add a new AlertCheck, managing state transitions and cooldown."""
        matches = self.evaluate_condition(calculated_value)
        targets_notified = {}

        # Determine the appropriate state for this check
        if matches:
            if self.state != "firing":
                # Transition to firing state and send a notification
                check_state = "firing"
                self.last_notified_at = datetime.now(UTC)
                targets_notified = self.notification_targets
            else:
                check_state = "firing"  # Already firing, no new notification
                matches = []  # Don't send duplicate notifications
        else:
            check_state = "not_met"
            self.state = "inactive"  # Set the Alert to inactive if the threshold is no longer met
            # Optionally send a resolved notification

        alert_check = AlertCheck.objects.create(
            alert_configuration=self,
            calculated_value=calculated_value,
            condition=self.condition,
            targets_notified=targets_notified,
            state=check_state,
            error_message=error_message,
        )

        # Update the Alert state
        if check_state == "firing":
            self.state = "firing"
        elif check_state == "not_met":
            self.state = "inactive"

        self.save()
        return alert_check, matches


class AlertCheck(UUIDModel):
    alert_configuration = models.ForeignKey(AlertConfiguration, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    calculated_value = models.FloatField(null=True, blank=True)
    condition = models.JSONField(default=dict)  # Snapshot of the condition at the time of the check
    targets_notified = models.JSONField(default=dict)
    error_message = models.TextField(null=True, blank=True)

    STATE_CHOICES = [
        ("firing", "Firing"),
        ("not_met", "Not Met"),
    ]
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="not_met")

    def __str__(self):
        return f"AlertCheck for {self.alert_configuration.name} at {self.created_at}"
