from __future__ import annotations

from decimal import Decimal
from typing import cast

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from posthog.models.utils import UUIDModel, uuid7


class BillingAlertConfiguration(UUIDModel):
    class Metric(models.TextChoices):
        SPEND = "spend", "Spend"

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
    # Team deletion is handled by the billing-alert re-home flow so an organization-scoped alert is preserved.
    team = models.ForeignKey(
        "posthog.Team",
        db_column="execution_team_id",
        db_constraint=False,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_by_id = models.BigIntegerField(null=True, blank=True)
    updated_by_id = models.BigIntegerField(null=True, blank=True)

    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)

    metric = models.CharField(max_length=20, choices=Metric.choices, default=Metric.SPEND)
    currency = models.CharField(max_length=3, default="USD")
    configuration_revision = models.PositiveIntegerField(default=1)

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
    pending_evaluation_date = models.DateField(null=True, blank=True)
    retry_attempt_count = models.PositiveSmallIntegerField(default=0)
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
        constraints = [
            models.CheckConstraint(
                condition=Q(baseline_window_days__gte=1),
                name="billing_alert_baseline_window_positive",
            ),
            models.CheckConstraint(
                condition=Q(check_interval_hours__in=(1, 2, 3, 4, 6, 8, 12, 24)),
                name="billing_alert_supported_interval",
            ),
            models.CheckConstraint(condition=Q(minimum_value__gte=0), name="billing_alert_minimum_nonnegative"),
            models.CheckConstraint(
                condition=(
                    Q(
                        threshold_type="relative_increase",
                        threshold_percentage__isnull=False,
                        threshold_percentage__gt=0,
                    )
                    | Q(
                        threshold_type__in=("absolute_value", "absolute_increase"),
                        threshold_value__isnull=False,
                        threshold_value__gte=0,
                    )
                ),
                name="billing_alert_threshold_configuration_valid",
            ),
        ]

    @property
    def execution_team_id(self) -> int:
        if self.team_id is None:
            raise ValueError("Billing alert does not have an execution team.")
        return cast(int, self.team_id)

    def __str__(self) -> str:
        return f"{self.name} ({self.organization_id})"

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


class BillingAlertEvaluationClaim(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        EVALUATING = "evaluating", "Evaluating"
        RETRYABLE = "retryable", "Retryable"
        COMPLETED = "completed", "Completed"
        SUPERSEDED = "superseded", "Superseded"

    alert = models.ForeignKey(BillingAlertConfiguration, on_delete=models.CASCADE, related_name="evaluation_claims")
    organization_id = models.UUIDField(db_index=True)
    evaluation_date = models.DateField()
    configuration_revision = models.PositiveIntegerField()
    delivery_uuid = models.UUIDField(default=uuid7, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "billing_alerts_evaluation_claim"
        constraints = [
            models.UniqueConstraint(
                fields=["alert", "evaluation_date", "configuration_revision"],
                name="unique_billing_alert_evaluation_claim",
            )
        ]
        indexes = [
            models.Index(fields=["organization_id", "-created_at"], name="billing_claim_org_created_idx"),
            models.Index(fields=["status", "next_retry_at"], name="billing_claim_retry_idx"),
        ]


class BillingAlertEvent(UUIDModel):
    class Source(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        MANUAL = "manual", "Manual"

    class Kind(models.TextChoices):
        CHECK = "check", "Check"
        FIRING = "firing", "Firing"
        RESOLVED = "resolved", "Resolved"
        ERRORED = "errored", "Errored"
        BROKEN_CONFIG = "broken_config", "Broken config"

    alert = models.ForeignKey(BillingAlertConfiguration, on_delete=models.CASCADE, related_name="events")
    claim = models.ForeignKey(BillingAlertEvaluationClaim, on_delete=models.CASCADE, related_name="attempts")
    organization_id = models.UUIDField(db_index=True)
    # Preserve the original execution team ID as audit history after that team is deleted.
    team = models.ForeignKey("posthog.Team", db_constraint=False, on_delete=models.DO_NOTHING, related_name="+")
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.CHECK)
    source = models.CharField(max_length=16, choices=Source.choices)
    attempt_number = models.PositiveIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)
    evaluation_date = models.DateField(null=True, blank=True)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)

    metric = models.CharField(max_length=20, choices=BillingAlertConfiguration.Metric.choices)
    current_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    baseline_value = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    absolute_delta = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    relative_delta_percentage = models.DecimalField(max_digits=28, decimal_places=6, null=True, blank=True)
    threshold_value_snapshot = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    threshold_percentage_snapshot = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    minimum_value_snapshot = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    threshold_breached = models.BooleanField(default=False)

    state_before = models.CharField(max_length=20, null=True, blank=True)
    state_after = models.CharField(max_length=20, null=True, blank=True)
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    targets_notified = models.JSONField(default=dict)

    query_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=80, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    is_transient_error = models.BooleanField(default=False)

    reason = models.TextField(blank=True)
    payload = models.JSONField(default=dict)

    class Meta:
        db_table = "billing_alerts_event"
        indexes = [
            models.Index(fields=["team", "-created_at"], name="billing_event_team_ts_idx"),
            models.Index(fields=["alert", "-created_at"], name="billing_event_alert_ts_idx"),
            models.Index(fields=["alert", "evaluation_date"], name="billing_event_alert_date_idx"),
            models.Index(fields=["kind", "-created_at"], name="billing_event_kind_ts_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["claim", "attempt_number"],
                name="unique_billing_alert_evaluation_attempt",
            )
        ]
