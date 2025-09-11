from datetime import UTC, datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import models

import pydantic

from posthog.schema import AlertCalculationInterval, AlertState, InsightThreshold

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.insight import Insight
from posthog.models.utils import CreatedMetaFields, UUIDTModel
from posthog.schema_migrations.upgrade_manager import upgrade_query

ALERT_STATE_CHOICES = [
    (AlertState.FIRING, AlertState.FIRING),
    (AlertState.NOT_FIRING, AlertState.NOT_FIRING),
    (AlertState.ERRORED, AlertState.ERRORED),
    (AlertState.SNOOZED, AlertState.SNOOZED),
]


def are_alerts_supported_for_insight(insight: Insight) -> bool:
    with upgrade_query(insight):
        query = insight.query
        while query.get("source"):
            query = query["source"]
        if query is None or query.get("kind") != "TrendsQuery":
            return False
    return True


# TODO: Enable `@deprecated` once we move to Python 3.13
# @deprecated("AlertConfiguration should be used instead.")
class Alert(models.Model):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)

    name = models.CharField(max_length=100)
    target_value = models.TextField()
    anomaly_condition = models.JSONField(default=dict)


class Threshold(ModelActivityMixin, CreatedMetaFields, UUIDTModel):
    """
    Threshold holds the configuration for a threshold. This can either be attached to an alert, or used as a standalone
    object for other purposes.
    """

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)

    name = models.CharField(max_length=255, blank=True)
    configuration = models.JSONField(default=dict)

    def clean(self):
        try:
            config = InsightThreshold.model_validate(self.configuration)
        except pydantic.ValidationError as e:
            raise ValidationError(f"Invalid threshold configuration: {e}")

        if not config or not config.bounds:
            return
        if config.bounds.lower is not None and config.bounds.upper is not None:
            if config.bounds.lower > config.bounds.upper:
                raise ValidationError("Lower threshold must be less than upper threshold")


class AlertConfiguration(ModelActivityMixin, CreatedMetaFields, UUIDTModel):
    ALERTS_ALLOWED_ON_FREE_TIER = 2

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)

    name = models.CharField(max_length=255, blank=True)
    subscribed_users = models.ManyToManyField(
        "posthog.User",
        through="posthog.AlertSubscription",
        through_fields=("alert_configuration", "user"),
        related_name="alert_configurations",
    )

    # insight specific config for the alert
    config = models.JSONField(default=dict, null=True, blank=True)

    # how often to recalculate the alert
    CALCULATION_INTERVAL_CHOICES = [
        (AlertCalculationInterval.HOURLY, AlertCalculationInterval.HOURLY.value),
        (AlertCalculationInterval.DAILY, AlertCalculationInterval.DAILY.value),
        (AlertCalculationInterval.WEEKLY, AlertCalculationInterval.WEEKLY.value),
        (AlertCalculationInterval.MONTHLY, AlertCalculationInterval.MONTHLY.value),
    ]
    calculation_interval = models.CharField(
        max_length=10,
        choices=CALCULATION_INTERVAL_CHOICES,
        default=AlertCalculationInterval.DAILY,
        null=True,
        blank=True,
    )

    # The threshold to evaluate the alert against. If null, the alert must have other conditions to trigger.
    threshold = models.ForeignKey(Threshold, on_delete=models.CASCADE, null=True, blank=True)
    condition = models.JSONField(default=dict)

    state = models.CharField(max_length=10, choices=ALERT_STATE_CHOICES, default=AlertState.NOT_FIRING)
    enabled = models.BooleanField(default=True)
    is_calculating = models.BooleanField(default=False, null=True, blank=True)

    last_notified_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    # UTC time for when next alert check is due
    next_check_at = models.DateTimeField(null=True, blank=True)
    # UTC time until when we shouldn't check alert/notify user
    snoozed_until = models.DateTimeField(null=True, blank=True)

    skip_weekend = models.BooleanField(null=True, blank=True, default=False)

    def __str__(self):
        return f"{self.name} (Team: {self.team})"

    def save(self, *args, **kwargs):
        if not self.enabled:
            # When disabling an alert, set the state to not firing
            self.state = AlertState.NOT_FIRING
            if "update_fields" in kwargs:
                kwargs["update_fields"].append("state")

        super().save(*args, **kwargs)


class AlertSubscription(ModelActivityMixin, CreatedMetaFields, UUIDTModel):
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


class AlertCheck(UUIDTModel):
    alert_configuration = models.ForeignKey(AlertConfiguration, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    calculated_value = models.FloatField(null=True, blank=True)
    condition = models.JSONField(default=dict)  # Snapshot of the condition at the time of the check
    targets_notified = models.JSONField(default=dict)
    error = models.JSONField(null=True, blank=True)

    state = models.CharField(max_length=10, choices=ALERT_STATE_CHOICES, default=AlertState.NOT_FIRING)

    def __str__(self):
        return f"AlertCheck for {self.alert_configuration.name} at {self.created_at}"

    @classmethod
    def clean_up_old_checks(cls) -> int:
        retention_days = 14
        oldest_allowed_date = datetime.now(UTC) - timedelta(days=retention_days)
        rows_count, _ = cls.objects.filter(created_at__lt=oldest_allowed_date).delete()
        return rows_count
