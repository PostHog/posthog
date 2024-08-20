from datetime import datetime, UTC, timedelta
from typing import Any, Optional

from django.db import models

from posthog.models.insight import Insight
from posthog.models.utils import UUIDModel, CreatedMetaFields
from posthog.schema import AlertCondition, InsightThreshold


def are_alerts_supported_for_insight(insight: Insight) -> bool:
    query = insight.query
    if query is None or query.get("kind") != "TrendsQuery":
        return False
    if query.get("trendsFilter", {}).get("display") != "BoldNumber":
        return False
    return True


class ConditionValidator:
    def __init__(self, threshold: Optional[InsightThreshold], condition: AlertCondition):
        self.threshold = threshold
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
        if not self.threshold:
            return []

        thresholds = self.threshold.absoluteThreshold
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


class Threshold(CreatedMetaFields, UUIDModel):
    """
    Threshold holds the configuration for a threshold. This can either be attached to an alert, or used as a standalone
    object for other purposes.
    """

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)

    name = models.CharField(max_length=255, blank=True)
    configuration = models.JSONField(default=dict)

    def clean(self):
        config = InsightThreshold.model_validate(self.configuration)
        if not config or not config.absoluteThreshold:
            return
        if config.absoluteThreshold.lower is not None and config.absoluteThreshold.upper is not None:
            if config.absoluteThreshold.lower > config.absoluteThreshold.upper:
                raise ValueError("Lower threshold must be less than upper threshold")


class AlertConfiguration(CreatedMetaFields, UUIDModel):
    ALERTS_PER_TEAM = 10

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)

    name = models.CharField(max_length=255, blank=True)
    subscribed_users = models.ManyToManyField(
        "posthog.User",
        through="AlertSubscription",
        through_fields=("alert_configuration", "user"),
        related_name="alert_configurations",
    )

    # The threshold to evaluate the alert against. If null, the alert must have other conditions to trigger.
    threshold = models.ForeignKey(Threshold, on_delete=models.CASCADE, null=True, blank=True)
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

    def save(self, *args, **kwargs):
        if not self.enabled:
            # When disabling an alert, set the state to inactive
            self.state = "inactive"
            if "update_fields" in kwargs:
                kwargs["update_fields"].append("state")

        super().save(*args, **kwargs)

    def evaluate_condition(self, calculated_value) -> list[str]:
        threshold = InsightThreshold.model_validate(self.threshold.configuration) if self.threshold else None
        condition = AlertCondition.model_validate(self.condition)
        validator = ConditionValidator(threshold=threshold, condition=condition)
        return validator.validate(calculated_value)

    def add_check(
        self, *, calculated_value: Optional[float], error: Optional[dict] = None
    ) -> tuple["AlertCheck", list[str]]:
        """Add a new AlertCheck, managing state transitions and cooldown."""
        matches = self.evaluate_condition(calculated_value) if calculated_value is not None else []
        targets_notified = {}

        # Determine the appropriate state for this check
        if matches:
            if self.state != "firing":
                # Transition to firing state and send a notification
                check_state = "firing"
                self.last_notified_at = datetime.now(UTC)
                targets_notified = {"users": list(self.subscribed_users.all().values_list("email", flat=True))}
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
            error=error,
        )

        # Update the Alert state
        if check_state == "firing":
            self.state = "firing"
        elif check_state == "not_met":
            self.state = "inactive"

        self.save()
        return alert_check, matches


class AlertSubscription(CreatedMetaFields, UUIDModel):
    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        limit_choices_to={
            "is_active": True,
            "organization_id": models.OuterRef("alert_configuration__team__organization_id"),
        },
        related_name="alert_subscriptions",
    )
    alert_configuration = models.ForeignKey(AlertConfiguration, on_delete=models.CASCADE)
    subscribed = models.BooleanField(default=True)

    def __str__(self):
        return f"AlertSubscription for {self.alert_configuration.name} by {self.user.email}"

    class Meta:
        unique_together = ["user", "alert_configuration"]


class AlertCheck(UUIDModel):
    alert_configuration = models.ForeignKey(AlertConfiguration, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    calculated_value = models.FloatField(null=True, blank=True)
    condition = models.JSONField(default=dict)  # Snapshot of the condition at the time of the check
    targets_notified = models.JSONField(default=dict)
    error = models.JSONField(null=True, blank=True)

    STATE_CHOICES = [
        ("firing", "Firing"),
        ("not_met", "Not Met"),
    ]
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="not_met")

    def __str__(self):
        return f"AlertCheck for {self.alert_configuration.name} at {self.created_at}"

    @classmethod
    def clean_up_old_checks(cls) -> int:
        retention_days = 14
        oldest_allowed_date = datetime.now(UTC) - timedelta(days=retention_days)
        rows_count, _ = cls.objects.filter(created_at__lt=oldest_allowed_date).delete()
        return rows_count
