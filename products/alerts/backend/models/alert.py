from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import models

if TYPE_CHECKING:
    from posthog.event_usage import AnalyticsProps
    from posthog.models.organization import Organization
    from posthog.models.user import User

import pydantic

from posthog.constants import AvailableFeature
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import CreatedMetaFields, UUIDTModel
from posthog.schema_enums import AlertCalculationInterval, AlertState

ALERT_STATE_CHOICES = [
    (AlertState.FIRING, AlertState.FIRING),
    (AlertState.NOT_FIRING, AlertState.NOT_FIRING),
    (AlertState.ERRORED, AlertState.ERRORED),
    (AlertState.SNOOZED, AlertState.SNOOZED),
]


class InvestigationStatus(models.TextChoices):
    PENDING = "pending", "pending"
    RUNNING = "running", "running"
    DONE = "done", "done"
    FAILED = "failed", "failed"
    SKIPPED = "skipped", "skipped"


class InvestigationVerdict(models.TextChoices):
    """The investigation agent's call on whether the firing alert was real.

    We keep this independent from InvestigationStatus so that status tracks the
    pipeline (did it run?) while verdict tracks the conclusion (was it real?).
    Future work may let users override this field manually.
    """

    TRUE_POSITIVE = "true_positive", "true_positive"
    FALSE_POSITIVE = "false_positive", "false_positive"
    INCONCLUSIVE = "inconclusive", "inconclusive"


def derive_detector_event_fields(detector_config: dict | None) -> dict:
    """Shared derivation of alert_mode/detector_type/ensemble_operator from a detector config.

    Used by both `alert created`/`alert updated` user-action events and the
    `$insight_alert_firing` internal event so the taxonomy stays in one place.
    """
    detector_config = detector_config or {}
    detector_type = detector_config.get("type")
    return {
        "alert_mode": "detector" if detector_type else "threshold",
        "detector_type": detector_type,
        "ensemble_operator": detector_config.get("operator") if detector_type == "ensemble" else None,
    }


# TODO: Enable `@deprecated` once we move to Python 3.13
# @deprecated("AlertConfiguration should be used instead.")
class Alert(models.Model):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("product_analytics.Insight", on_delete=models.CASCADE)

    name = models.CharField(max_length=100)
    target_value = models.TextField()
    anomaly_condition = models.JSONField(default=dict)

    class Meta:
        db_table = "posthog_alert"


class Threshold(ModelActivityMixin, CreatedMetaFields, UUIDTModel):
    """
    Threshold holds the configuration for a threshold. This can either be attached to an alert, or used as a standalone
    object for other purposes.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("product_analytics.Insight", on_delete=models.CASCADE)

    name = models.CharField(max_length=255, blank=True)
    configuration = models.JSONField(default=dict)

    class Meta:
        db_table = "posthog_threshold"

    def clean(self) -> None:
        try:
            # Deferred: posthog.schema (the pydantic models) stays off django.setup(),
            # where this model loads in every process.
            from posthog.schema import InsightThreshold  # noqa: PLC0415

            config = InsightThreshold.model_validate(self.configuration)
        except pydantic.ValidationError as e:
            raise ValidationError(f"Invalid threshold configuration: {e}")

        if not config or not config.bounds:
            return
        if config.bounds.lower is not None and config.bounds.upper is not None:
            if config.bounds.lower > config.bounds.upper:
                raise ValidationError("Lower threshold must be less than upper threshold")


class AlertConfiguration(ModelActivityMixin, CreatedMetaFields, UUIDTModel):
    ALERTS_ALLOWED_ON_FREE_TIER = 5

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("product_analytics.Insight", on_delete=models.CASCADE)

    name = models.CharField(max_length=255, blank=True)
    subscribed_users = models.ManyToManyField(
        "posthog.User",
        through="alerts.AlertSubscription",
        through_fields=("alert_configuration", "user"),
        related_name="alert_configurations",
    )

    # insight specific config for the alert
    config = models.JSONField(default=dict, null=True, blank=True)

    # how often to recalculate the alert
    CALCULATION_INTERVAL_CHOICES = [
        (AlertCalculationInterval.EVERY_15_MINUTES, AlertCalculationInterval.EVERY_15_MINUTES.value),
        (AlertCalculationInterval.HOURLY, AlertCalculationInterval.HOURLY.value),
        (AlertCalculationInterval.DAILY, AlertCalculationInterval.DAILY.value),
        (AlertCalculationInterval.WEEKLY, AlertCalculationInterval.WEEKLY.value),
        (AlertCalculationInterval.MONTHLY, AlertCalculationInterval.MONTHLY.value),
    ]
    calculation_interval = models.CharField(
        max_length=20,
        choices=CALCULATION_INTERVAL_CHOICES,
        default=AlertCalculationInterval.DAILY,
        null=True,
        blank=True,
    )

    # The threshold to evaluate the alert against. If null, the alert must have other conditions to trigger.
    threshold = models.ForeignKey(Threshold, on_delete=models.CASCADE, null=True, blank=True)
    condition = models.JSONField(default=dict)

    # Detector-based anomaly detection configuration (alternative to threshold)
    detector_config = models.JSONField(null=True, blank=True)

    state = models.CharField(max_length=10, choices=ALERT_STATE_CHOICES, default=AlertState.NOT_FIRING)
    enabled = models.BooleanField(default=True)

    last_notified_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    # UTC time for when next alert check is due
    next_check_at = models.DateTimeField(null=True, blank=True)
    # UTC time until when we shouldn't check alert/notify user
    snoozed_until = models.DateTimeField(null=True, blank=True)

    skip_weekend = models.BooleanField(null=True, blank=True, default=False)

    schedule_restriction = models.JSONField(null=True, blank=True, default=None)

    # When enabled and the alert transitions to FIRING, an investigation agent runs
    # and writes its findings to a linked Notebook. Only effective for detector-based
    # (anomaly) alerts. See posthog/temporal/alerts/workflows.py for the trigger logic.
    investigation_agent_enabled = models.BooleanField(default=False)

    # When enabled (and investigation_agent_enabled is on), notification dispatch is
    # held until the investigation agent produces a verdict — and suppressed if the
    # verdict is false_positive. A safety-net Temporal workflow force-notifies after a
    # grace period if the investigation stalls, so users can never silently miss a
    # real fire. See posthog/temporal/alerts/workflows.py (RunInvestigationSafetyNetWorkflow).
    investigation_gates_notifications = models.BooleanField(default=False)

    # What to do with an "inconclusive" verdict when notifications are gated.
    # Default is notify — safest for anomaly alerts where the agent not being sure
    # is itself informative.
    INVESTIGATION_INCONCLUSIVE_ACTION_CHOICES = [
        ("notify", "Notify"),
        ("suppress", "Suppress"),
    ]
    investigation_inconclusive_action = models.CharField(
        max_length=10,
        choices=INVESTIGATION_INCONCLUSIVE_ACTION_CHOICES,
        default="notify",
    )

    class Meta:
        db_table = "posthog_alertconfiguration"

    def __str__(self) -> str:
        return f"{self.name} (Team: {self.team})"

    @property
    def is_high_frequency_interval(self) -> bool:
        # Real-time counts as high frequency so its checks always run fresh ClickHouse
        # queries (CALCULATE_BLOCKING_ALWAYS) instead of reading a possibly stale cache.
        return self.calculation_interval in (
            AlertCalculationInterval.EVERY_15_MINUTES,
            AlertCalculationInterval.REAL_TIME,
        )

    @property
    def is_real_time_interval(self) -> bool:
        return self.calculation_interval == AlertCalculationInterval.REAL_TIME

    def get_subscribed_users_emails(self) -> list[str]:
        return list(
            self.subscribed_users.filter(organization_membership__organization=self.team.organization).values_list(
                "email", flat=True
            )
        )

    def mark_for_recheck(self, *, reset_state: bool = False) -> list[str]:
        """Returns list of field names that were modified (for use with update_fields)."""
        updated: list[str] = []
        if reset_state:
            self.state = AlertState.NOT_FIRING
            updated.append("state")
        self.next_check_at = None
        updated.append("next_check_at")
        return updated

    def save(self, *args, **kwargs) -> None:
        if not self.enabled:
            # When disabling an alert, set the state to not firing
            self.state = AlertState.NOT_FIRING
            if "update_fields" in kwargs:
                kwargs["update_fields"].append("state")

        super().save(*args, **kwargs)

    def _get_event_properties(self) -> dict:
        detector_config = self.detector_config or {}
        detector_type = detector_config.get("type")

        ensemble_detector_types: list[str] | None = None
        has_preprocessing = False

        if detector_type == "ensemble":
            sub_detectors = detector_config.get("detectors") or []
            ensemble_detector_types = [sub.get("type") for sub in sub_detectors if sub.get("type")]
            has_preprocessing = any(sub.get("preprocessing") for sub in sub_detectors)
        elif detector_type:
            has_preprocessing = bool(detector_config.get("preprocessing"))

        schedule_restriction = self.schedule_restriction
        has_schedule_restriction = False
        blocked_window_count: int | None = None
        if isinstance(schedule_restriction, dict):
            windows = schedule_restriction.get("blocked_windows")
            if isinstance(windows, list):
                blocked_window_count = len(windows)
                has_schedule_restriction = blocked_window_count > 0

        threshold_configuration: dict = {}
        if self.threshold and isinstance(self.threshold.configuration, dict):
            threshold_configuration = self.threshold.configuration
        threshold_bounds = threshold_configuration.get("bounds") or {}
        has_threshold = self.threshold is not None
        threshold_type = threshold_configuration.get("type") if has_threshold else None
        has_lower_bound = threshold_bounds.get("lower") is not None if has_threshold else False
        has_upper_bound = threshold_bounds.get("upper") is not None if has_threshold else False

        alert_config = self.config if isinstance(self.config, dict) else {}
        is_hogql_config = alert_config.get("type") == "HogQLAlertConfig"

        subscribed_users_count: int | None = None
        if self.pk is not None:
            subscribed_users_count = self.subscribed_users.count()

        return {
            "alert_id": self.id,
            "alert_name": self.name,
            "condition_type": self.condition.get("type") if self.condition else None,
            "calculation_interval": self.calculation_interval,
            "is_high_frequency_interval": self.is_high_frequency_interval,
            "enabled": self.enabled,
            "skip_weekend": bool(self.skip_weekend),
            "has_schedule_restriction": has_schedule_restriction,
            "has_threshold": has_threshold,
            "threshold_type": threshold_type,
            "has_lower_bound": has_lower_bound,
            "has_upper_bound": has_upper_bound,
            "config_type": alert_config.get("type"),
            "trends_series_index": alert_config.get("series_index"),
            "trends_check_ongoing_interval": alert_config.get("check_ongoing_interval"),
            "hogql_evaluation": (alert_config.get("evaluation") or "last_row") if is_hogql_config else None,
            "hogql_has_explicit_column": bool(alert_config.get("column")) if is_hogql_config else None,
            "hogql_has_label_column": bool(alert_config.get("label_column")) if is_hogql_config else None,
            "subscribed_users_count": subscribed_users_count,
            **derive_detector_event_fields(detector_config),
            "ensemble_detector_types": ensemble_detector_types,
            "has_preprocessing": has_preprocessing,
            "schedule_restriction_blocked_window_count": blocked_window_count,
        }

    def report_created(self, user: User, analytics_props: AnalyticsProps | None = None) -> None:
        from posthog.event_usage import report_user_action

        report_user_action(user, "alert created", self._get_event_properties(), analytics_props=analytics_props)

    def report_updated(self, user: User, analytics_props: AnalyticsProps | None = None) -> None:
        from posthog.event_usage import report_user_action

        report_user_action(user, "alert updated", self._get_event_properties(), analytics_props=analytics_props)

    @classmethod
    def check_alert_limit(cls, team_id: int, organization: Organization) -> str | None:
        """Return an error message if the team has reached its alert limit, else None."""
        alerts_feature = organization.get_available_feature(AvailableFeature.ALERTS)
        existing_count = cls.objects.filter(team_id=team_id).count()

        if alerts_feature:
            allowed = alerts_feature.get("limit")
            # If allowed is None then the user is allowed unlimited alerts
            if allowed is not None and existing_count >= allowed:
                return f"Your team has reached the limit of {allowed} alerts on your plan."
        else:
            # If the org doesn't have alerts feature, limit to that on free tier
            if existing_count >= cls.ALERTS_ALLOWED_ON_FREE_TIER:
                return f"Your plan is limited to {cls.ALERTS_ALLOWED_ON_FREE_TIER} alerts."

        return None

    @classmethod
    def supports_high_frequency_intervals(cls, organization: Organization) -> bool:
        return organization.is_feature_available(AvailableFeature.HIGH_FREQUENCY_ALERTS)

    @classmethod
    def every_15_minutes_interval_validation_error(
        cls,
        *,
        calculation_interval: str | AlertCalculationInterval | None,
        organization: Organization,
    ) -> str | None:
        if calculation_interval != AlertCalculationInterval.EVERY_15_MINUTES:
            return None
        if not cls.supports_high_frequency_intervals(organization):
            return "15-minute alert intervals require a Boost, Scale, or Enterprise platform add-on."
        return None

    @classmethod
    def supports_real_time_intervals(cls, organization: Organization) -> bool:
        return organization.is_feature_available(AvailableFeature.REAL_TIME_ALERTS)

    @classmethod
    def real_time_interval_validation_error(
        cls,
        *,
        calculation_interval: str | AlertCalculationInterval | None,
        organization: Organization,
    ) -> str | None:
        if calculation_interval != AlertCalculationInterval.REAL_TIME:
            return None
        if not cls.supports_real_time_intervals(organization):
            return "Real-time alert intervals require a Scale or Enterprise plan."
        return None

    @classmethod
    def check_real_time_alert_limit(cls, team_id: int, organization: Organization) -> str | None:
        """Return an error message if the team has reached its real-time alert limit, else None.

        Unlike check_alert_limit (which counts every alert against the ALERTS feature), this
        counts only real-time alerts against the REAL_TIME_ALERTS feature's limit. Orgs without
        the feature are already blocked by real_time_interval_validation_error.
        """
        feature = organization.get_available_feature(AvailableFeature.REAL_TIME_ALERTS)
        if not feature:
            return None

        allowed = feature.get("limit")
        # If allowed is None then the org is allowed unlimited real-time alerts
        if allowed is None:
            return None

        existing_count = cls.objects.filter(
            team_id=team_id, calculation_interval=AlertCalculationInterval.REAL_TIME
        ).count()
        if existing_count >= allowed:
            return f"Your team has reached the limit of {allowed} real-time alerts on your plan."
        return None


class AlertSubscription(ModelActivityMixin, CreatedMetaFields, UUIDTModel):
    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        limit_choices_to={
            "is_active": True,
            "organization_id": models.OuterRef("alert_configuration__team__organization_id"),
        },
        related_name="alert_subscriptions",
    )
    alert_configuration = models.ForeignKey(AlertConfiguration, on_delete=models.CASCADE)
    subscribed = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"AlertSubscription for {self.alert_configuration.name} by {self.user.email}"

    class Meta:
        unique_together = ["user", "alert_configuration"]
        db_table = "posthog_alertsubscription"


class AlertCheck(UUIDTModel):
    alert_configuration = models.ForeignKey(AlertConfiguration, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    calculated_value = models.FloatField(null=True, blank=True)
    condition = models.JSONField(default=dict)  # Snapshot of the condition at the time of the check
    targets_notified = models.JSONField(default=dict)
    error = models.JSONField(null=True, blank=True)

    state = models.CharField(max_length=10, choices=ALERT_STATE_CHOICES, default=AlertState.NOT_FIRING)

    # Detector-based anomaly detection results
    anomaly_scores = models.JSONField(null=True, blank=True)  # Scores for each data point
    triggered_points = models.JSONField(null=True, blank=True)  # Indices of detected anomalies
    triggered_dates = models.JSONField(null=True, blank=True)  # Dates for chart alignment
    interval = models.CharField(max_length=10, null=True, blank=True)  # Insight interval when check was created
    triggered_metadata = models.JSONField(
        null=True, blank=True
    )  # Additional trigger context (e.g. series_index, breakdown_value)

    # Investigation agent linkage — populated when the alert transitions to FIRING and
    # investigation_agent_enabled is true. Lives on the check record so the notebook is
    # surfaced inline with the specific firing event it investigated.
    investigation_status = models.CharField(max_length=10, choices=InvestigationStatus.choices, null=True, blank=True)
    investigation_verdict = models.CharField(max_length=20, choices=InvestigationVerdict.choices, null=True, blank=True)
    investigation_notebook = models.ForeignKey(
        "notebooks.Notebook",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # Short plain-text summary the agent emits. Safe to show inline in lists, emails,
    # and Slack follow-ups so a user can decide whether to click into the notebook.
    investigation_summary = models.TextField(null=True, blank=True)
    investigation_error = models.JSONField(null=True, blank=True)

    # Populated when a notification is dispatched for this check. Lets the gating
    # logic be idempotent across retries and is the audit trail for "when did the
    # user actually get pinged?" when the investigation agent is gating notifications.
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    # True when the investigation agent concluded false_positive (or inconclusive
    # with suppress policy) and we skipped dispatching the notification. Surfaced
    # in the UI so users can audit which fires the agent swallowed.
    notification_suppressed_by_agent = models.BooleanField(default=False)

    class Meta:
        db_table = "posthog_alertcheck"

    def __str__(self) -> str:
        return f"AlertCheck for {self.alert_configuration.name} at {self.created_at}"

    @classmethod
    def clean_up_old_checks(cls) -> int:
        retention_days = 14
        oldest_allowed_date = datetime.now(UTC) - timedelta(days=retention_days)
        rows_count, _ = cls.objects.filter(created_at__lt=oldest_allowed_date).delete()
        return rows_count
