from __future__ import annotations

from decimal import Decimal
from functools import cached_property

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from posthog.models.organization import Organization
from posthog.models.utils import UUIDModel

MAX_FAILURES_BEFORE_BROKEN = 5


class BillingAlertConfiguration(UUIDModel):
    class Metric(models.TextChoices):
        SPEND = "spend", "Spend"
        USAGE = "usage", "Usage"

    class GroupBy(models.TextChoices):
        TOTAL = "total", "Total"
        USAGE_TYPE = "usage_type", "Usage type"
        TEAM = "team", "Team"
        USAGE_TYPE_TEAM = "usage_type_team", "Usage type and team"

    class ThresholdType(models.TextChoices):
        RELATIVE_INCREASE = "relative_increase", "Relative increase"
        ABSOLUTE_VALUE = "absolute_value", "Absolute value"
        ABSOLUTE_INCREASE = "absolute_increase", "Absolute increase"

    class State(models.TextChoices):
        NOT_FIRING = "not_firing", "Not firing"
        FIRING = "firing", "Firing"
        ERRORED = "errored", "Errored"
        SNOOZED = "snoozed", "Snoozed"
        BROKEN = "broken", "Broken"

    organization_id = models.UUIDField(db_index=True)
    execution_team_id = models.BigIntegerField(db_index=True)
    created_by_id = models.BigIntegerField(null=True, blank=True)
    updated_by_id = models.BigIntegerField(null=True, blank=True)

    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)

    metric = models.CharField(max_length=20, choices=Metric.choices, default=Metric.SPEND)
    currency = models.CharField(max_length=3, default="USD")
    usage_types = models.JSONField(default=list)
    team_ids = models.JSONField(default=list)
    group_by = models.CharField(max_length=32, choices=GroupBy.choices, default=GroupBy.TOTAL)

    threshold_type = models.CharField(
        max_length=32,
        choices=ThresholdType.choices,
        default=ThresholdType.RELATIVE_INCREASE,
    )
    threshold_percentage = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    threshold_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    minimum_value = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal("0"))
    baseline_window_days = models.PositiveSmallIntegerField(default=7)
    evaluation_delay_hours = models.PositiveSmallIntegerField(default=6)

    state = models.CharField(max_length=20, choices=State.choices, default=State.NOT_FIRING)
    check_interval_hours = models.PositiveSmallIntegerField(default=24)
    cooldown_hours = models.PositiveSmallIntegerField(default=24)
    snooze_until = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        db_table = "billing_alerts_configuration"
        indexes = [
            models.Index(fields=["organization_id", "-created_at"], name="billing_alert_org_created_idx"),
            models.Index(fields=["enabled", "next_check_at"], name="billing_alert_scheduler_idx"),
            models.Index(fields=["organization_id", "enabled", "state"], name="billing_alert_org_state_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.organization_id})"

    @cached_property
    def organization(self) -> Organization:
        return Organization.objects.get(id=self.organization_id)

    def clean(self) -> None:
        super().clean()

        if self.baseline_window_days < 1:
            raise ValidationError({"baseline_window_days": "Must be at least 1."})
        if self.check_interval_hours < 1:
            raise ValidationError({"check_interval_hours": "Must be at least 1."})
        if self.minimum_value < 0:
            raise ValidationError({"minimum_value": "Must be greater than or equal to 0."})

        if self.threshold_type == self.ThresholdType.RELATIVE_INCREASE:
            if self.threshold_percentage is None:
                raise ValidationError({"threshold_percentage": "Required for relative increase alerts."})
            if self.threshold_percentage <= 0:
                raise ValidationError({"threshold_percentage": "Must be greater than 0."})
        elif self.threshold_type in (self.ThresholdType.ABSOLUTE_VALUE, self.ThresholdType.ABSOLUTE_INCREASE):
            if self.threshold_value is None:
                raise ValidationError({"threshold_value": "Required for absolute threshold alerts."})
            if self.threshold_value < 0:
                raise ValidationError({"threshold_value": "Must be greater than or equal to 0."})


class BillingAlertEvent(UUIDModel):
    class Kind(models.TextChoices):
        CHECK = "check", "Check"
        FIRING = "firing", "Firing"
        RESOLVED = "resolved", "Resolved"
        ERRORED = "errored", "Errored"
        SNOOZED = "snoozed", "Snoozed"
        UNSNOOZED = "unsnoozed", "Unsnoozed"
        ENABLED = "enabled", "Enabled"
        DISABLED = "disabled", "Disabled"
        THRESHOLD_CHANGED = "threshold_changed", "Threshold changed"
        BROKEN_CONFIG = "broken_config", "Broken config"

    alert = models.ForeignKey(BillingAlertConfiguration, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.CHECK)

    created_at = models.DateTimeField(auto_now_add=True)
    evaluation_date = models.DateField(null=True, blank=True)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)

    metric = models.CharField(max_length=20, choices=BillingAlertConfiguration.Metric.choices)
    current_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    baseline_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    absolute_delta = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    relative_delta_percentage = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    threshold_value_snapshot = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    threshold_percentage_snapshot = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    minimum_value_snapshot = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    threshold_breached = models.BooleanField(default=False)

    state_before = models.CharField(max_length=20, null=True, blank=True)
    state_after = models.CharField(max_length=20, null=True, blank=True)
    notification_sent_at = models.DateTimeField(null=True, blank=True)

    query_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=80, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    is_transient_error = models.BooleanField(default=False)

    reason = models.TextField(blank=True)
    payload = models.JSONField(default=dict)

    class Meta:
        db_table = "billing_alerts_event"
        indexes = [
            models.Index(fields=["alert", "-created_at"], name="billing_event_alert_ts_idx"),
            models.Index(fields=["alert", "evaluation_date"], name="billing_event_alert_date_idx"),
            models.Index(fields=["kind", "-created_at"], name="billing_event_kind_ts_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["alert", "kind", "evaluation_date"],
                condition=Q(evaluation_date__isnull=False),
                name="unique_billing_alert_event_date",
            )
        ]


class BillingAlertDelivery(UUIDModel):
    class DestinationType(models.TextChoices):
        SLACK = "slack", "Slack"
        WEBHOOK = "webhook", "Webhook"
        TEAMS = "teams", "Microsoft Teams"
        EMAIL = "email", "Email"
        IN_APP = "in_app", "In-app"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    event = models.ForeignKey(BillingAlertEvent, on_delete=models.CASCADE, related_name="deliveries")
    destination_type = models.CharField(max_length=32, choices=DestinationType.choices)
    destination_key = models.CharField(max_length=255)
    hog_function_id = models.UUIDField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    recipient_results = models.JSONField(default=dict)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "billing_alerts_delivery"
        indexes = [
            models.Index(fields=["event", "destination_type"], name="bill_deliv_event_type_idx"),
            models.Index(fields=["status", "-created_at"], name="bill_deliv_status_ts_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "destination_type", "destination_key"],
                name="unique_billing_delivery_destination",
            )
        ]
