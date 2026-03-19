import dataclasses
from typing import Optional
from zoneinfo import ZoneInfo

from django.db.models import OuterRef, QuerySet, Subquery
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.schema import AlertCondition, AlertState, DetectorConfig, InsightThreshold, TrendsAlertConfig

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
from posthog.schema_migrations.upgrade_manager import upgrade_query
from posthog.tasks.alerts.utils import validate_alert_config
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
        ]
        read_only_fields = fields

    def get_targets_notified(self, instance: AlertCheck) -> bool:
        return instance.targets_notified != {}


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
        help_text="The last 5 alert check results (only populated on retrieve).",
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
        allow_null=True,
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
        help_text="Skip alert evaluation on weekends (Saturday and Sunday).",
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
            "config",
            "detector_config",
            "calculation_interval",
            "snoozed_until",
            "skip_weekend",
            "last_value",
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

        instance = super().update(instance, validated_data)
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

        return validated.model_dump() if hasattr(validated, "model_dump") else value

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

        try:
            validate_alert_config(query, condition, config, threshold_config)
        except ValueError as e:
            raise ValidationError(str(e))

        # only validate alert count when creating a new alert
        if self.context["request"].method != "POST":
            return attrs

        if msg := AlertConfiguration.check_alert_limit(self.context["team_id"], self.context["get_organization"]()):
            raise ValidationError({"alert": [msg]})

        return attrs


class AlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "alert"
    queryset = AlertConfiguration.objects.all().order_by("-created_at")
    serializer_class = AlertSerializer

    def safely_get_queryset(self, queryset) -> QuerySet:
        filters = self.request.query_params
        if "insight" in filters:
            queryset = queryset.filter(insight_id=filters["insight"])

        latest_check = AlertCheck.objects.filter(alert_configuration=OuterRef("pk")).order_by("-created_at")
        queryset = queryset.annotate(last_value=Subquery(latest_check.values("calculated_value")[:1]))

        return queryset

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.checks = instance.alertcheck_set.all().order_by("-created_at")[:5]
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        insight_id = request.GET.get("insight_id")
        if insight_id is not None:
            queryset = queryset.filter(insight=insight_id)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


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
