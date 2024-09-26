from datetime import datetime, UTC, timedelta
from typing import Any, Optional, cast
from dateutil.relativedelta import relativedelta


from django.db import models
from django.core.exceptions import ValidationError

from posthog.hogql_queries.legacy_compatibility.flagged_conversion_manager import conversion_to_query_based
from posthog.models.insight import Insight
from posthog.models.utils import UUIDModel, CreatedMetaFields
from posthog.schema import AlertCondition, InsightThreshold, AlertState, AlertCalculationInterval


ALERT_STATE_CHOICES = [
    (AlertState.FIRING, AlertState.FIRING),
    (AlertState.NOT_FIRING, AlertState.NOT_FIRING),
    (AlertState.ERRORED, AlertState.ERRORED),
]


def alert_calculation_interval_to_relativedelta(alert_calculation_interval: AlertCalculationInterval) -> relativedelta:
    match alert_calculation_interval:
        case AlertCalculationInterval.HOURLY:
            return relativedelta(hours=1)
        case AlertCalculationInterval.DAILY:
            return relativedelta(days=1)
        case AlertCalculationInterval.WEEKLY:
            return relativedelta(weeks=1)
        case AlertCalculationInterval.MONTHLY:
            return relativedelta(months=1)
        case _:
            raise ValueError(f"Invalid alert calculation interval: {alert_calculation_interval}")


def are_alerts_supported_for_insight(insight: Insight) -> bool:
    with conversion_to_query_based(insight):
        query = insight.query
        while query.get("source"):
            query = query["source"]
        if query is None or query.get("kind") != "TrendsQuery":
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
        breaches = []
        for validator in validators:
            breaches += validator(calculated_value)
        return breaches

    def validate_absolute_threshold(self, calculated_value: float) -> list[str]:
        if not self.threshold or not self.threshold.absoluteThreshold:
            return []

        absolute_threshold = self.threshold.absoluteThreshold
        if absolute_threshold.lower is not None and calculated_value < absolute_threshold.lower:
            return [f"The trend value ({calculated_value}) is below the lower threshold ({absolute_threshold.lower})"]
        if absolute_threshold.upper is not None and calculated_value > absolute_threshold.upper:
            return [f"The trend value ({calculated_value}) is above the upper threshold ({absolute_threshold.upper})"]
        return []


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
                raise ValidationError("Lower threshold must be less than upper threshold")


class AlertConfiguration(CreatedMetaFields, UUIDModel):
    ALERTS_PER_TEAM = 5

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
    config = models.JSONField()

    # how often to recalculate the alert
    CALCULATION_INTERVAL_CHOICES = [
        (AlertCalculationInterval.HOURLY, AlertCalculationInterval.HOURLY.value),
        (AlertCalculationInterval.DAILY, AlertCalculationInterval.DAILY.value),
        (AlertCalculationInterval.WEEKLY, AlertCalculationInterval.WEEKLY.value),
        (AlertCalculationInterval.MONTHLY, AlertCalculationInterval.MONTHLY.value),
    ]
    calculation_interval = models.CharField(
        max_length=10, choices=CALCULATION_INTERVAL_CHOICES, default=AlertCalculationInterval.DAILY
    )

    # The threshold to evaluate the alert against. If null, the alert must have other conditions to trigger.
    threshold = models.ForeignKey(Threshold, on_delete=models.CASCADE, null=True, blank=True)
    condition = models.JSONField(default=dict)

    state = models.CharField(max_length=10, choices=ALERT_STATE_CHOICES, default=AlertState.NOT_FIRING)
    enabled = models.BooleanField(default=True)

    last_notified_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} (Team: {self.team})"

    def save(self, *args, **kwargs):
        if not self.enabled:
            # When disabling an alert, set the state to not firing
            self.state = AlertState.NOT_FIRING
            if "update_fields" in kwargs:
                kwargs["update_fields"].append("state")

        super().save(*args, **kwargs)

    def evaluate_condition(self, calculated_value) -> list[str]:
        threshold = InsightThreshold.model_validate(self.threshold.configuration) if self.threshold else None
        condition = AlertCondition.model_validate(self.condition)
        validator = ConditionValidator(threshold=threshold, condition=condition)
        return validator.validate(calculated_value)

    def add_check(
        self, *, aggregated_value: Optional[float], error: Optional[dict] = None
    ) -> tuple["AlertCheck", list[str], Optional[dict], bool]:
        """
        Add a new AlertCheck, managing state transitions and cool down.

        Args:
            aggregated_value: result of insight calculation compressed to one number to compare against threshold
            error: any error raised while calculating insight value, if present then set state as errored
        """

        targets_notified: dict[str, list[str]] = {}
        breaches = []
        notify = False

        if not error:
            try:
                breaches = self.evaluate_condition(aggregated_value) if aggregated_value is not None else []
            except Exception as err:
                # error checking the condition
                error = {
                    "message": f"Error checking alert condition {str(err)}",
                }

        if error:
            # If the alert is not already errored, notify user
            if self.state != AlertState.ERRORED:
                self.state = AlertState.ERRORED
                notify = True
        elif breaches:
            # If the alert is not already firing, notify user
            if self.state != AlertState.FIRING:
                self.state = AlertState.FIRING
                notify = True
        else:
            self.state = AlertState.NOT_FIRING  # Set the Alert to not firing if the threshold is no longer met
            # TODO: Optionally send a resolved notification when alert goes from firing to not_firing?

        now = datetime.now(UTC)
        self.last_checked_at = datetime.now(UTC)

        # IMPORTANT: update next_check_at according to interval
        # ensure we don't recheck alert until the next interval is due
        self.next_check_at = (self.next_check_at or now) + alert_calculation_interval_to_relativedelta(
            cast(AlertCalculationInterval, self.calculation_interval)
        )

        if notify:
            self.last_notified_at = now
            targets_notified = {"users": list(self.subscribed_users.all().values_list("email", flat=True))}

        alert_check = AlertCheck.objects.create(
            alert_configuration=self,
            calculated_value=aggregated_value,
            condition=self.condition,
            targets_notified=targets_notified,
            state=self.state,
            error=error,
        )

        self.save()
        return alert_check, breaches, error, notify


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

    state = models.CharField(max_length=10, choices=ALERT_STATE_CHOICES, default=AlertState.NOT_FIRING)

    def __str__(self):
        return f"AlertCheck for {self.alert_configuration.name} at {self.created_at}"

    @classmethod
    def clean_up_old_checks(cls) -> int:
        retention_days = 14
        oldest_allowed_date = datetime.now(UTC) - timedelta(days=retention_days)
        rows_count, _ = cls.objects.filter(created_at__lt=oldest_allowed_date).delete()
        return rows_count
