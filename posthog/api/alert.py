import dataclasses
from typing import Optional
from zoneinfo import ZoneInfo

from django.db.models import OuterRef, QuerySet, Subquery
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.schema import (
    AlertCalculationInterval,
    AlertCondition,
    AlertState,
    DetectorConfig,
    InsightThreshold,
    TrendsAlertConfig,
)

from posthog.api.alert_schedule_restriction import AlertScheduleRestriction
from posthog.api.documentation import extend_schema_field
from posthog.api.insight import InsightBasicSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import get_request_analytics_properties
from posthog.models import Insight, User
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.alert import AlertCheck, AlertConfiguration, AlertSubscription, Threshold
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.resource_limits import LimitKey, check_count_limit
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.tasks.alerts.detector import MAX_DETECTOR_BREAKDOWN_VALUES
from posthog.tasks.alerts.schedule_restriction import validate_and_normalize_schedule_restriction
from posthog.tasks.alerts.utils import next_check_at_after_schedule_restriction_change, validate_alert_config
from posthog.utils import relative_date_parse


@extend_schema_field(InsightThreshold)  # type: ignore[arg-type]
class ThresholdConfigurationField(serializers.JSONField):
    pass


@extend_schema_field(AlertCondition)  # type: ignore[arg-type]
class AlertConditionField(serializers.JSONField):
    pass


@extend_schema_field(TrendsAlertConfig)  # type: ignore[arg-type]
class TrendsAlertConfigField(serializers.JSONField):
    pass


@extend_schema_field(DetectorConfig)  # type: ignore[arg-type]
class DetectorConfigField(serializers.JSONField):
    pass


@extend_schema_field(AlertScheduleRestriction)  # type: ignore[arg-type]
class ScheduleRestrictionField(serializers.JSONField):
    pass


class ThresholdSerializer(serializers.ModelSerializer):
    configuration = ThresholdConfigurationField(
        help_text="Threshold bounds and type. Includes bounds (lower/upper floats) and type (absolute or percentage).",
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional name for the threshold.",
    )

    class Meta:
        model = Threshold
        fields = [
            "id",
            "created_at",
            "name",
            "configuration",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]

    def validate(self, data):
        instance = Threshold(**data)
        instance.clean()
        return data


class AlertCheckSerializer(serializers.ModelSerializer):
    targets_notified = serializers.SerializerMethodField()
    investigation_notebook_short_id = serializers.SerializerMethodField(
        help_text="Short ID of the Notebook produced by the investigation agent, when the agent ran for this check."
    )

    class Meta:
        model = AlertCheck
        fields = [
            "id",
            "created_at",
            "calculated_value",
            "state",
            "targets_notified",
            "anomaly_scores",
            "triggered_points",
            "triggered_dates",
            "interval",
            "triggered_metadata",
            "investigation_status",
            "investigation_verdict",
            "investigation_summary",
            "investigation_notebook_short_id",
            "notification_sent_at",
            "notification_suppressed_by_agent",
        ]
        read_only_fields = fields

    def get_targets_notified(self, instance: AlertCheck) -> bool:
        return instance.targets_notified != {}

    def get_investigation_notebook_short_id(self, instance: AlertCheck) -> str | None:
        notebook = instance.investigation_notebook
        return notebook.short_id if notebook is not None else None


class AlertSubscriptionSerializer(serializers.ModelSerializer):
    # nosemgrep: unscoped-primary-key-related-field — User model is not team-scoped; validate() checks team membership
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), required=True)

    class Meta:
        model = AlertSubscription
        fields = ["id", "user", "alert_configuration"]
        read_only_fields = ["id", "alert_configuration"]

    def validate(self, data):
        user: User = data["user"]
        alert_configuration = data["alert_configuration"]

        if not user.teams.filter(pk=alert_configuration.team_id).exists():
            raise serializers.ValidationError("User does not belong to the same organization as the alert's team.")

        return data


@extend_schema_field(
    {
        "type": "string",
        "nullable": True,
        "description": "Snooze the alert until this time. Pass a relative date string (e.g. '2h', '1d') or null to unsnooze.",
    }
)
class RelativeDateTimeField(serializers.DateTimeField):
    def to_internal_value(self, data):
        return data


class AlertSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    checks = AlertCheckSerializer(
        many=True,
        read_only=True,
        help_text="Alert check results. By default returns the last 5. Use checks_date_from and checks_date_to (e.g. '-24h', '-7d') to get checks within a time window, checks_limit to cap how many are returned (default 5, max 500), and checks_offset to skip the newest N checks for pagination (0-based). Newest checks first. Only populated on retrieve.",
    )
    checks_total = serializers.SerializerMethodField(
        read_only=True,
        help_text="Total alert checks matching the retrieve filters (date window). Only set on alert retrieve; omitted otherwise.",
    )
    threshold = ThresholdSerializer(
        help_text="Threshold configuration with bounds and type for evaluating the alert.",
    )
    condition = AlertConditionField(
        required=False,
        allow_null=True,
        help_text="Alert condition type. Determines how the value is evaluated: absolute_value, relative_increase, or relative_decrease.",
    )
    config = TrendsAlertConfigField(
        required=False,
        allow_null=True,
        help_text="Trends-specific alert configuration. Includes series_index (which series to monitor) and check_ongoing_interval (whether to check the current incomplete interval).",
    )
    detector_config = DetectorConfigField(required=False, allow_null=True)
    insight = TeamScopedPrimaryKeyRelatedField(
        queryset=Insight.objects.all(),
        help_text="Insight ID monitored by this alert. Note: Response returns full InsightBasicSerializer object.",
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Human-readable name for the alert.",
    )
    # nosemgrep: unscoped-primary-key-related-field — User model is not team-scoped; validate_subscribed_users() checks team membership
    subscribed_users = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        many=True,
        required=True,
        allow_empty=True,
        help_text="User IDs to subscribe to this alert. Note: Response returns full UserBasicSerializer object.",
    )
    enabled = serializers.BooleanField(
        required=False,
        help_text="Whether the alert is actively being evaluated.",
    )
    calculation_interval = serializers.ChoiceField(
        choices=AlertConfiguration.CALCULATION_INTERVAL_CHOICES,
        required=False,
        help_text="How often the alert is checked: hourly, daily, weekly, or monthly.",
    )
    snoozed_until = RelativeDateTimeField(
        allow_null=True,
        required=False,
        help_text="Snooze the alert until this time. Pass a relative date string (e.g. '2h', '1d') or null to unsnooze.",
    )
    skip_weekend = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Skip alert evaluation on weekends (Saturday and Sunday, local to project timezone).",
    )
    schedule_restriction = ScheduleRestrictionField(
        required=False,
        allow_null=True,
        help_text="Blocked local time windows (HH:MM in the project timezone). Interval is half-open [start, end): "
        "start inclusive, end exclusive. Use blocked_windows array of {start, end}. Null disables.",
    )
    investigation_agent_enabled = serializers.BooleanField(
        required=False,
        help_text="When enabled, an investigation agent runs on the state transition to firing and writes findings to a Notebook linked from the alert check. Only effective for detector-based (anomaly) alerts.",
    )
    investigation_gates_notifications = serializers.BooleanField(
        required=False,
        help_text="When enabled (and investigation_agent_enabled is on), notification dispatch is held until the investigation agent produces a verdict. Notifications are suppressed when the verdict is false_positive (and optionally when inconclusive). A safety-net task force-fires after a few minutes if the investigation stalls.",
    )
    investigation_inconclusive_action = serializers.ChoiceField(
        choices=[("notify", "Notify"), ("suppress", "Suppress")],
        required=False,
        help_text="How to handle an 'inconclusive' verdict when notifications are gated. 'notify' is the safe default — an agent that can't be sure is itself useful signal.",
    )
    state = serializers.CharField(
        read_only=True,
        help_text="Current alert state: Firing, Not firing, Errored, or Snoozed.",
    )
    last_value = serializers.FloatField(
        read_only=True,
        allow_null=True,
        help_text="The last calculated value from the most recent alert check.",
    )

    def get_checks_total(self, obj: AlertConfiguration) -> int | None:
        return getattr(obj, "checks_total", None)

    class Meta:
        model = AlertConfiguration
        fields = [
            "id",
            "created_by",
            "created_at",
            "insight",
            "name",
            "subscribed_users",
            "threshold",
            "condition",
            "state",
            "enabled",
            "last_notified_at",
            "last_checked_at",
            "next_check_at",
            "checks",
            "checks_total",
            "config",
            "detector_config",
            "calculation_interval",
            "snoozed_until",
            "skip_weekend",
            "schedule_restriction",
            "last_value",
            "investigation_agent_enabled",
            "investigation_gates_notifications",
            "investigation_inconclusive_action",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "state",
            "last_notified_at",
            "last_checked_at",
            "next_check_at",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["subscribed_users"] = UserBasicSerializer(instance.subscribed_users.all(), many=True, read_only=True).data
        data["insight"] = InsightBasicSerializer(instance.insight).data
        if data.get("checks_total") is None:
            data.pop("checks_total", None)
        return data

    def add_threshold(self, threshold_data, validated_data):
        threshold_instance = Threshold.objects.create(
            **threshold_data,
            team_id=self.context["team_id"],
            created_by=self.context["request"].user,
            insight_id=validated_data["insight"].id,
        )
        return threshold_instance

    def create(self, validated_data: dict) -> AlertConfiguration:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        team = self.context["get_team"]()
        current_count = AlertConfiguration.objects.filter(team_id=team.id).count()
        check_count_limit(
            team=team,
            key=LimitKey.MAX_ALERTS_PER_TEAM,
            current_count=current_count,
            user=self.context["request"].user,
        )
        subscribed_users = validated_data.pop("subscribed_users")
        threshold_data = validated_data.pop("threshold", None)

        if threshold_data:
            threshold_instance = self.add_threshold(threshold_data, validated_data)
            validated_data["threshold"] = threshold_instance

        instance: AlertConfiguration = super().create(validated_data)

        for user in subscribed_users:
            AlertSubscription.objects.create(
                user=user, alert_configuration=instance, created_by=self.context["request"].user
            )

        instance.report_created(
            self.context["request"].user,
            analytics_props=get_request_analytics_properties(self.context["request"]),
        )
        return instance

    def update(self, instance, validated_data):
        if "snoozed_until" in validated_data:
            snoozed_until_param = validated_data.pop("snoozed_until")

            if snoozed_until_param is None:
                instance.state = AlertState.NOT_FIRING
                instance.snoozed_until = None
            else:
                # always store snoozed_until as UTC time
                # as we look at current UTC time to check when to run alerts
                snoozed_until = relative_date_parse(
                    snoozed_until_param, ZoneInfo("UTC"), increase=True, always_truncate=True
                )
                instance.state = AlertState.SNOOZED
                instance.snoozed_until = snoozed_until

            AlertCheck.objects.create(
                alert_configuration=instance,
                calculated_value=None,
                condition=instance.condition,
                targets_notified={},
                state=instance.state,
                error=None,
            )

        conditions_or_threshold_changed = False

        threshold_data = validated_data.pop("threshold", None)
        if threshold_data is not None:
            if threshold_data == {}:
                instance.threshold = None
                conditions_or_threshold_changed = True
            elif instance.threshold:
                previous_threshold_configuration = instance.threshold.configuration
                threshold_instance = instance.threshold
                for key, value in threshold_data.items():
                    setattr(threshold_instance, key, value)
                threshold_instance.save()
                if previous_threshold_configuration != threshold_instance.configuration:
                    conditions_or_threshold_changed = True
            else:
                threshold_instance = self.add_threshold(threshold_data, validated_data)
                validated_data["threshold"] = threshold_instance
                conditions_or_threshold_changed = True

        subscribed_users = validated_data.pop("subscribed_users", None)
        if subscribed_users is not None:
            AlertSubscription.objects.filter(alert_configuration=instance).exclude(user__in=subscribed_users).delete()
            for user in subscribed_users:
                # nosemgrep: idor-lookup-without-team (user team membership validated by viewset)
                AlertSubscription.objects.get_or_create(
                    user=user, alert_configuration=instance, defaults={"created_by": self.context["request"].user}
                )

        calculation_interval_changed = (
            "calculation_interval" in validated_data
            and validated_data["calculation_interval"] != instance.calculation_interval
        )
        if conditions_or_threshold_changed or calculation_interval_changed:
            instance.mark_for_recheck(reset_state=conditions_or_threshold_changed)

        schedule_restriction_changed = False
        if "schedule_restriction" in validated_data:
            new_sr = validated_data["schedule_restriction"]
            if new_sr != instance.schedule_restriction:
                schedule_restriction_changed = True

        instance = super().update(instance, validated_data)
        if schedule_restriction_changed:
            instance.next_check_at = next_check_at_after_schedule_restriction_change(instance)
            instance.save(update_fields=["next_check_at"])

        instance.report_updated(
            self.context["request"].user,
            analytics_props=get_request_analytics_properties(self.context["request"]),
        )
        return instance

    def validate_detector_config(self, value):
        if value is None:
            return value

        import pydantic

        try:
            validated = DetectorConfig.model_validate(value)
        except pydantic.ValidationError:
            raise ValidationError("Invalid detector configuration.")

        # Ensemble requires at least 2 sub-detectors
        root = validated.root if hasattr(validated, "root") else validated
        if getattr(root, "type", None) == "ensemble" and hasattr(root, "detectors"):
            if len(root.detectors) < 2:
                raise ValidationError("Ensemble detector requires at least 2 sub-detectors.")
            for sub in root.detectors:
                sub_dict: dict = sub.model_dump() if hasattr(sub, "model_dump") else sub  # type: ignore[assignment]
                self._validate_detector_params(sub_dict)
        else:
            self._validate_detector_params(value)

        return validated.model_dump() if hasattr(validated, "model_dump") else value

    @staticmethod
    def _validate_detector_params(config: dict) -> None:
        """Validate detector parameter ranges match frontend constraints."""
        # Parameter ranges: (min, max, name)
        PARAM_RANGES: dict[str, tuple[float, float, str]] = {
            "threshold": (0.0, 1.0, "Sensitivity threshold"),
            "window": (5, 1000, "Window size"),
            "n_estimators": (10, 500, "Number of trees"),
            "n_neighbors": (1, 50, "Number of neighbors"),
            "n_bins": (5, 50, "Number of bins"),
            "multiplier": (0.5, 10.0, "IQR multiplier"),
            "training_offset_n": (1, 500, "Training offset"),
        }

        for param, (min_val, max_val, label) in PARAM_RANGES.items():
            val = config.get(param)
            if val is not None:
                if val < min_val or val > max_val:
                    raise ValidationError(f"{label} must be between {min_val} and {max_val}.")

        preprocessing = config.get("preprocessing")
        if preprocessing and isinstance(preprocessing, dict):
            smooth_n = preprocessing.get("smooth_n")
            if smooth_n is not None and (smooth_n < 0 or smooth_n > 30):
                raise ValidationError("Smoothing window must be between 0 and 30.")
            lags_n = preprocessing.get("lags_n")
            if lags_n is not None and (lags_n < 0 or lags_n > 10):
                raise ValidationError("Lag features must be between 0 and 10.")

    def validate_snoozed_until(self, value):
        if value is not None and not isinstance(value, str):
            raise ValidationError("snoozed_until has to be passed in string format")

        return value

    def validate_insight(self, value):
        if value and not value.are_alerts_supported:
            raise ValidationError("Alerts are not supported for this insight.")
        return value

    def validate_subscribed_users(self, value):
        for user in value:
            if not user.teams.filter(pk=self.context["team_id"]).exists():
                raise ValidationError("User does not belong to the same organization as the alert's team.")
        return value

    def validate_schedule_restriction(self, value):
        try:
            return validate_and_normalize_schedule_restriction(value)
        except ValueError:
            raise serializers.ValidationError("Invalid schedule restriction.")

    def validate(self, attrs):
        if attrs.get("insight") and attrs["insight"].team.id != self.context["team_id"]:
            raise ValidationError({"insight": ["This insight does not belong to your team."]})

        condition = attrs.get("condition", self.instance.condition if self.instance else None)
        config = attrs.get("config", self.instance.config if self.instance else None)
        insight = attrs.get("insight") or (self.instance.insight if self.instance else None)
        if insight is None:
            raise ValidationError({"insight": ["Insight is required."]})
        with upgrade_query(insight):
            query = insight.query
            if query is None:
                raise ValidationError({"insight": ["Insight has no valid query."]})

        threshold_config = None
        if "threshold" in attrs and isinstance(attrs["threshold"], dict):
            threshold_config = attrs["threshold"].get("configuration")
        elif self.instance and self.instance.threshold:
            threshold_config = self.instance.threshold.configuration

        calculation_interval = attrs.get(
            "calculation_interval",
            self.instance.calculation_interval if self.instance else AlertCalculationInterval.DAILY,
        )

        try:
            validate_alert_config(query, condition, config, threshold_config, calculation_interval)
        except ValueError as e:
            raise ValidationError(str(e))

        # Investigation agent is only supported for detector-based alerts.
        investigation_enabled = attrs.get(
            "investigation_agent_enabled",
            self.instance.investigation_agent_enabled if self.instance else False,
        )
        if investigation_enabled:
            detector_config = attrs.get(
                "detector_config",
                self.instance.detector_config if self.instance else None,
            )
            if not detector_config:
                raise ValidationError(
                    {
                        "investigation_agent_enabled": [
                            "Investigation agent is only supported for anomaly detection alerts."
                        ]
                    }
                )

        # Notification gating only makes sense when the investigation agent is on —
        # otherwise there's no verdict to wait for and the safety-net task would
        # end up being the only notifier, which defeats the feature.
        gates_notifications = attrs.get(
            "investigation_gates_notifications",
            self.instance.investigation_gates_notifications if self.instance else False,
        )
        if gates_notifications and not investigation_enabled:
            raise ValidationError(
                {
                    "investigation_gates_notifications": [
                        "Notification gating requires investigation_agent_enabled=true."
                    ]
                }
            )

        # only validate alert count when creating a new alert
        if self.context["request"].method != "POST":
            return attrs

        if msg := AlertConfiguration.check_alert_limit(self.context["team_id"], self.context["get_organization"]()):
            raise ValidationError({"alert": [msg]})

        return attrs


class AlertSimulateSerializer(serializers.Serializer):
    insight = TeamScopedPrimaryKeyRelatedField(
        queryset=Insight.objects.all(),
        help_text="Insight ID to simulate the detector on.",
    )
    detector_config = DetectorConfigField(
        help_text="Detector configuration to simulate.",
    )
    series_index = serializers.IntegerField(
        default=0,
        help_text="Zero-based index of the series to analyze.",
    )
    date_from = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Relative date string for how far back to simulate (e.g. '-24h', '-30d', '-4w'). "
        "If not provided, uses the detector's minimum required samples.",
    )

    def validate_detector_config(self, value):
        if value is None:
            raise ValidationError("detector_config is required.")

        import pydantic

        try:
            validated = DetectorConfig.model_validate(value)
        except pydantic.ValidationError:
            raise ValidationError("Invalid detector configuration.")

        root = validated.root if hasattr(validated, "root") else validated
        if getattr(root, "type", None) == "ensemble" and hasattr(root, "detectors"):
            if len(root.detectors) < 2:
                raise ValidationError("Ensemble detector requires at least 2 sub-detectors.")
            for sub in root.detectors:
                sub_dict: dict = sub.model_dump() if hasattr(sub, "model_dump") else sub  # type: ignore[assignment]
                AlertSerializer._validate_detector_params(sub_dict)
        else:
            AlertSerializer._validate_detector_params(value)

        return validated.model_dump() if hasattr(validated, "model_dump") else value


class BreakdownSimulationResultSerializer(serializers.Serializer):
    label = serializers.CharField(help_text="Breakdown value label.")  # type: ignore[assignment]
    data = serializers.ListField(child=serializers.FloatField(), help_text="Data values for each point.")  # type: ignore[assignment]
    dates = serializers.ListField(child=serializers.CharField(), help_text="Date labels for each point.")
    scores = serializers.ListField(
        child=serializers.FloatField(allow_null=True),
        help_text="Anomaly score for each point.",
    )
    triggered_indices = serializers.ListField(
        child=serializers.IntegerField(), help_text="Indices of points flagged as anomalies."
    )
    triggered_dates = serializers.ListField(
        child=serializers.CharField(), help_text="Dates of points flagged as anomalies."
    )
    total_points = serializers.IntegerField(help_text="Total number of data points analyzed.")
    anomaly_count = serializers.IntegerField(help_text="Number of anomalies detected.")
    sub_detector_scores = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text="Per-sub-detector scores for ensemble detectors.",
    )


class AlertSimulateResponseSerializer(serializers.Serializer):
    data = serializers.ListField(child=serializers.FloatField(), help_text="Data values for each point.")  # type: ignore[assignment]
    dates = serializers.ListField(child=serializers.CharField(), help_text="Date labels for each point.")
    scores = serializers.ListField(
        child=serializers.FloatField(allow_null=True),
        help_text="Anomaly score for each point (null if insufficient data).",
    )
    triggered_indices = serializers.ListField(
        child=serializers.IntegerField(), help_text="Indices of points flagged as anomalies."
    )
    triggered_dates = serializers.ListField(
        child=serializers.CharField(), help_text="Dates of points flagged as anomalies."
    )
    interval = serializers.CharField(
        allow_null=True, help_text="Interval of the trends query (hour, day, week, month)."
    )
    total_points = serializers.IntegerField(help_text="Total number of data points analyzed.")
    anomaly_count = serializers.IntegerField(help_text="Number of anomalies detected.")
    sub_detector_scores = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text="Per-sub-detector scores for ensemble detectors. Each entry has 'type' and 'scores' fields.",
    )
    breakdown_results = BreakdownSimulationResultSerializer(
        many=True,
        required=False,
        help_text=f"Per-breakdown-value simulation results. Present only when the insight has breakdowns (up to {MAX_DETECTOR_BREAKDOWN_VALUES} values).",
    )


class AlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "alert"
    queryset = AlertConfiguration.objects.select_related("team", "insight").order_by("-created_at")
    serializer_class = AlertSerializer

    def safely_get_queryset(self, queryset) -> QuerySet:
        filters = self.request.query_params
        if "insight" in filters:
            queryset = queryset.filter(insight_id=filters["insight"])

        latest_check = AlertCheck.objects.filter(alert_configuration=OuterRef("pk")).order_by("-created_at")
        queryset = queryset.annotate(last_value=Subquery(latest_check.values("calculated_value")[:1]))

        return queryset

    CHECKS_DEFAULT_LIMIT = 5
    CHECKS_MAX_LIMIT = 500

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="checks_date_from",
                type=str,
                required=False,
                description="Relative date string for the start of the check history window (e.g. '-24h', '-7d', '-14d'). Returns checks created after this time. Max retention is 14 days.",
            ),
            OpenApiParameter(
                name="checks_date_to",
                type=str,
                required=False,
                description="Relative date string for the end of the check history window (e.g. '-1h', '-1d'). Defaults to now if not specified.",
            ),
            OpenApiParameter(
                name="checks_limit",
                type=int,
                required=False,
                description="Maximum number of check results to return (default 5, max 500). Applied after date filtering.",
            ),
            OpenApiParameter(
                name="checks_offset",
                type=int,
                required=False,
                description="Number of newest checks to skip (0-based). Use with checks_limit for pagination. Default 0.",
            ),
        ],
    )
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()

        checks_qs = instance.alertcheck_set.select_related("investigation_notebook").order_by("-created_at")

        checks_date_from = request.query_params.get("checks_date_from")
        if checks_date_from:
            parsed_date = relative_date_parse(checks_date_from, ZoneInfo("UTC"))
            checks_qs = checks_qs.filter(created_at__gte=parsed_date)

        checks_date_to = request.query_params.get("checks_date_to")
        if checks_date_to:
            parsed_date = relative_date_parse(checks_date_to, ZoneInfo("UTC"))
            checks_qs = checks_qs.filter(created_at__lte=parsed_date)

        has_date_filter = checks_date_from or checks_date_to
        raw_limit = request.query_params.get("checks_limit")
        if raw_limit is not None:
            try:
                limit = max(1, min(int(raw_limit), self.CHECKS_MAX_LIMIT))
            except (ValueError, TypeError):
                limit = self.CHECKS_DEFAULT_LIMIT
        else:
            limit = self.CHECKS_MAX_LIMIT if has_date_filter else self.CHECKS_DEFAULT_LIMIT

        raw_offset = request.query_params.get("checks_offset")
        if raw_offset is not None:
            try:
                offset = max(0, int(raw_offset))
            except (ValueError, TypeError):
                offset = 0
        else:
            offset = 0

        checks_total = checks_qs.count()
        instance.checks_total = checks_total
        offset = min(offset, checks_total)
        instance.checks = checks_qs[offset : offset + limit]
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        insight_id = request.GET.get("insight_id")
        if insight_id is not None:
            queryset = queryset.filter(insight=insight_id)

        # Paginate first, then prefetch checks only for the page
        page = self.paginate_queryset(queryset)
        alerts = list(page) if page is not None else list(queryset)

        # Prefetch firing checks for anomaly point display on chart.
        if alerts:
            alert_ids = [a.id for a in alerts]
            firing_checks = (
                AlertCheck.objects.filter(
                    alert_configuration_id__in=alert_ids,
                    triggered_points__isnull=False,
                )
                .exclude(triggered_points=[])
                .select_related("investigation_notebook")
                .order_by("-created_at")
            )
            checks_by_alert: dict[str, list] = {str(a.id): [] for a in alerts}
            for check in firing_checks:
                checks_by_alert.setdefault(str(check.alert_configuration_id), []).append(check)
            for alert in alerts:
                alert.checks = checks_by_alert.get(str(alert.id), [])

        if page is not None:
            serializer = self.get_serializer(alerts, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(alerts, many=True)
        return Response(serializer.data)

    @extend_schema(
        request=AlertSimulateSerializer,
        responses={200: AlertSimulateResponseSerializer},
        description="Simulate a detector on an insight's historical data. Read-only — no AlertCheck records are created.",
    )
    @action(detail=False, methods=["POST"], url_path="simulate", required_scopes=["alert:read"])
    def simulate(self, request, *args, **kwargs):
        from posthog.tasks.alerts.detector import simulate_detector_on_insight

        serializer = AlertSimulateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)

        insight = serializer.validated_data["insight"]
        detector_config = serializer.validated_data["detector_config"]
        series_index = serializer.validated_data["series_index"]
        date_from = serializer.validated_data.get("date_from")

        try:
            result = simulate_detector_on_insight(
                insight=insight,
                team=self.team,
                detector_config=detector_config,
                series_index=series_index,
                date_from=date_from,
            )
        except (ValueError, IndexError) as e:
            raise ValidationError(str(e))
        except RuntimeError:
            raise ValidationError("Simulation failed: unable to compute results for this insight.")

        response_serializer = AlertSimulateResponseSerializer(result)
        return Response(response_serializer.data)


class ThresholdWithAlertSerializer(ThresholdSerializer):
    alerts = AlertSerializer(many=True, read_only=True, source="alertconfiguration_set")

    class Meta(ThresholdSerializer.Meta):
        fields = [*ThresholdSerializer.Meta.fields, "alerts"]
        read_only_fields = [*ThresholdSerializer.Meta.read_only_fields, "alerts"]


class ThresholdViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "alert"
    queryset = Threshold.objects.all()
    serializer_class = ThresholdWithAlertSerializer


@dataclasses.dataclass(frozen=True)
class AlertConfigurationContext(ActivityContextBase):
    insight_id: Optional[int] = None
    insight_short_id: Optional[str] = None
    insight_name: Optional[str] = "Insight"
    alert_id: Optional[int] = None
    alert_name: Optional[str] = "Alert"


@dataclasses.dataclass(frozen=True)
class AlertSubscriptionContext(AlertConfigurationContext):
    subscriber_name: Optional[str] = None
    subscriber_email: Optional[str] = None


@mutable_receiver(model_activity_signal, sender=AlertConfiguration)
def handle_alert_configuration_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name or f"Alert for {after_update.insight.name}",
            context=AlertConfigurationContext(
                insight_id=after_update.insight_id,
                insight_short_id=after_update.insight.short_id,
                insight_name=after_update.insight.name,
            ),
        ),
    )


@mutable_receiver(model_activity_signal, sender=Threshold)
def handle_threshold_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    alert_config = None
    if hasattr(after_update, "alertconfiguration_set"):
        alert_config = after_update.alertconfiguration_set.first()

    if alert_config:
        log_activity(
            organization_id=alert_config.team.organization_id,
            team_id=alert_config.team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=alert_config.id,
            scope="AlertConfiguration",
            activity=activity,
            detail=Detail(
                changes=changes_between("Threshold", previous=before_update, current=after_update),
                type="threshold_change",
                context=AlertConfigurationContext(
                    insight_id=alert_config.insight_id,
                    insight_short_id=alert_config.insight.short_id,
                    insight_name=alert_config.insight.name,
                    alert_name=alert_config.name,
                ),
            ),
        )


@mutable_receiver(model_activity_signal, sender=AlertSubscription)
def handle_alert_subscription_change(before_update, after_update, activity, user, was_impersonated=False, **kwargs):
    alert_config = after_update.alert_configuration

    if alert_config:
        log_activity(
            organization_id=alert_config.team.organization_id,
            team_id=alert_config.team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=alert_config.id,
            scope="AlertConfiguration",
            activity=activity,
            detail=Detail(
                changes=changes_between("AlertSubscription", previous=before_update, current=after_update),
                type="alert_subscription_change",
                context=AlertSubscriptionContext(
                    insight_id=alert_config.insight_id,
                    insight_short_id=alert_config.insight.short_id,
                    insight_name=alert_config.insight.name,
                    subscriber_name=after_update.user.get_full_name(),
                    subscriber_email=after_update.user.email,
                    alert_name=alert_config.name,
                ),
            ),
        )


@receiver(pre_delete, sender=AlertConfiguration)
def cleanup_alert_hog_functions(sender, instance: AlertConfiguration, **kwargs):
    from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType

    for hog_function in HogFunction.objects.filter(
        team_id=instance.team_id,
        type=HogFunctionType.INTERNAL_DESTINATION,
        deleted=False,
        filters__contains={"properties": [{"key": "alert_id", "value": str(instance.id)}]},
    ):
        hog_function.enabled = False
        hog_function.deleted = True
        hog_function.save()


@receiver(pre_delete, sender=AlertSubscription)
def handle_alert_subscription_delete(sender, instance, **kwargs):
    from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated

    alert_config = instance.alert_configuration

    if alert_config:
        log_activity(
            organization_id=alert_config.team.organization_id,
            team_id=alert_config.team_id,
            user=get_current_user(),
            was_impersonated=get_was_impersonated(),
            item_id=alert_config.id,
            scope="AlertConfiguration",
            activity="deleted",
            detail=Detail(
                type="alert_subscription_change",
                context=AlertSubscriptionContext(
                    insight_id=alert_config.insight_id,
                    insight_short_id=alert_config.insight.short_id,
                    insight_name=alert_config.insight.name,
                    subscriber_name=instance.user.get_full_name(),
                    subscriber_email=instance.user.email,
                    alert_name=alert_config.name,
                ),
            ),
        )
