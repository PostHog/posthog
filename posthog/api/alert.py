import dataclasses
from zoneinfo import ZoneInfo

from django.db.models import QuerySet
from django.db.models.signals import pre_delete
from django.dispatch import receiver

import numpy as np
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.schema import AlertCondition, AlertState, DetectorConfig, InsightThreshold, TrendsAlertConfig

from posthog.api.documentation import extend_schema_field
from posthog.api.insight import InsightBasicSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import AvailableFeature
from posthog.models import Insight, User
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.alert import (
    AlertCheck,
    AlertConfiguration,
    AlertSubscription,
    Threshold,
    are_alerts_supported_for_insight,
)
from posthog.models.signals import model_activity_signal, mutable_receiver
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
    configuration = ThresholdConfigurationField()

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


class RelativeDateTimeField(serializers.DateTimeField):
    def to_internal_value(self, data):
        return data


class AlertSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    checks = AlertCheckSerializer(many=True, read_only=True)
    threshold = ThresholdSerializer(required=False, allow_null=True)
    condition = AlertConditionField(required=False, allow_null=True)
    config = TrendsAlertConfigField(required=False, allow_null=True)
    detector_config = DetectorConfigField(required=False, allow_null=True)
    insight = serializers.PrimaryKeyRelatedField(
        queryset=Insight.objects.all(),
        help_text="Insight ID monitored by this alert. Note: Response returns full InsightBasicSerializer object.",
    )
    subscribed_users = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        many=True,
        required=True,
        allow_empty=True,
        help_text="User IDs to subscribe to this alert. Note: Response returns full UserBasicSerializer object.",
    )
    snoozed_until = RelativeDateTimeField(allow_null=True, required=False)

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
                AlertSubscription.objects.get_or_create(
                    user=user, alert_configuration=instance, defaults={"created_by": self.context["request"].user}
                )

        if conditions_or_threshold_changed:
            # If anything changed we set to NOT_FIRING, so it's firing and notifying with the new settings
            instance.state = AlertState.NOT_FIRING

        calculation_interval_changed = (
            "calculation_interval" in validated_data
            and validated_data["calculation_interval"] != instance.calculation_interval
        )
        if conditions_or_threshold_changed or calculation_interval_changed:
            # calculate alert right now, don't wait until preset time
            self.next_check_at = None

        return super().update(instance, validated_data)

    def validate_snoozed_until(self, value):
        if value is not None and not isinstance(value, str):
            raise ValidationError("snoozed_until has to be passed in string format")

        return value

    def validate_insight(self, value):
        if value and not are_alerts_supported_for_insight(value):
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

        # only validate alert count when creating a new alert
        if self.context["request"].method != "POST":
            return attrs

        user_org = self.context["request"].user.organization

        alerts_feature = user_org.get_available_feature(AvailableFeature.ALERTS)
        existing_alerts_count = AlertConfiguration.objects.filter(team_id=self.context["team_id"]).count()

        if alerts_feature:
            allowed_alerts_count = alerts_feature.get("limit")
            # If allowed_alerts_count is None then the user is allowed unlimited alerts
            if allowed_alerts_count is not None:
                # Check current count against allowed limit
                if existing_alerts_count >= allowed_alerts_count:
                    raise ValidationError(
                        {"alert": [f"Your team has reached the limit of {allowed_alerts_count} alerts on your plan."]}
                    )
        else:
            # If the org doesn't have alerts feature, limit to that on free tier
            if existing_alerts_count >= AlertConfiguration.ALERTS_ALLOWED_ON_FREE_TIER:
                raise ValidationError(
                    {"alert": [f"Your plan is limited to {AlertConfiguration.ALERTS_ALLOWED_ON_FREE_TIER} alerts"]}
                )

        return attrs


MAX_BACKFILL_OBSERVATIONS = 200


class BackfillRequestSerializer(serializers.Serializer):
    detector_config = DetectorConfigField(required=True)
    n_observations = serializers.IntegerField(min_value=10, max_value=MAX_BACKFILL_OBSERVATIONS, default=100)
    insight_id = serializers.IntegerField(required=True)
    series_index = serializers.IntegerField(default=0, min_value=0)
    alert_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="If provided, saves results as AlertCheck records"
    )


class AlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "alert"
    queryset = AlertConfiguration.objects.all().order_by("-created_at")
    serializer_class = AlertSerializer

    def safely_get_queryset(self, queryset) -> QuerySet:
        filters = self.request.query_params
        if "insight" in filters:
            queryset = queryset.filter(insight_id=filters["insight"])
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
        alerts = page if page is not None else list(queryset)

        # Populate checks for each alert (needed for anomaly points visualization)
        for alert in alerts:
            alert.checks = list(alert.alertcheck_set.all().order_by("-created_at")[:5])

        if page is not None:
            serializer = self.get_serializer(alerts, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(alerts, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def backfill(self, request, *args, **kwargs):
        """
        Run a detector on historical insight data and optionally save results as AlertCheck records.

        POST /api/projects/:team_id/alerts/backfill/

        Request body:
        - detector_config: DetectorConfig object
        - n_observations: number of data points to analyze (10-200)
        - insight_id: the insight to analyze
        - series_index: which series to analyze (for multi-series insights)
        - alert_id: (optional) if provided, saves results as AlertCheck records

        Returns:
        - triggered_indices: list of indices where anomalies were detected
        - scores: list of anomaly scores for each point
        - total_points: total number of points analyzed
        - anomaly_count: number of anomalies detected
        - data: the actual data values analyzed
        - saved_check_id: (if alert_id provided) the ID of the saved AlertCheck
        """
        from posthog.schema import IntervalType, TrendsQuery

        from posthog.api.services.query import ExecutionMode
        from posthog.caching.calculate_results import calculate_for_query_based_insight
        from posthog.schema_migrations.upgrade_manager import upgrade_query
        from posthog.tasks.alerts.detectors import get_detector
        from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS
        from posthog.utils import get_from_dict_or_attr

        serializer = BackfillRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Get the insight
        try:
            insight = Insight.objects.get(id=data["insight_id"], team_id=self.team_id)
        except Insight.DoesNotExist:
            return Response({"error": "Insight not found"}, status=status.HTTP_404_NOT_FOUND)

        detector_config = data["detector_config"]
        n_observations = data["n_observations"]
        series_index = data["series_index"]
        alert_id = data.get("alert_id")

        # Validate alert if provided
        alert = None
        if alert_id:
            try:
                alert = AlertConfiguration.objects.get(id=alert_id, team_id=self.team_id)
            except AlertConfiguration.DoesNotExist:
                return Response({"error": "Alert not found"}, status=status.HTTP_404_NOT_FOUND)

        # Get the query from insight
        with upgrade_query(insight):
            query = insight.query
            kind = get_from_dict_or_attr(query, "kind")

            if kind in WRAPPER_NODE_KINDS:
                query = get_from_dict_or_attr(query, "source")
                kind = get_from_dict_or_attr(query, "kind")

            if kind != "TrendsQuery":
                return Response(
                    {"error": f"Backfill is only supported for TrendsQuery, got {kind}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            query = TrendsQuery.model_validate(query)

        # Calculate date range for backfill
        match query.interval:
            case IntervalType.DAY:
                date_from = f"-{n_observations}d"
            case IntervalType.WEEK:
                date_from = f"-{n_observations}w"
            case IntervalType.MONTH:
                date_from = f"-{n_observations}m"
            case _:
                date_from = f"-{n_observations}h"

        filters_override = {"date_from": date_from}

        # Calculate insight results
        try:
            calculation_result = calculate_for_query_based_insight(
                insight,
                team=insight.team,
                execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                user=request.user,
                filters_override=filters_override,
            )
        except Exception as e:
            return Response({"error": f"Failed to calculate insight: {e!s}"}, status=status.HTTP_400_BAD_REQUEST)

        if not calculation_result.result:
            return Response({"error": "No results from insight calculation"}, status=status.HTTP_400_BAD_REQUEST)

        # Pick the series
        results = calculation_result.result
        if series_index >= len(results):
            return Response(
                {"error": f"Series index {series_index} out of range (insight has {len(results)} series)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        selected_series = results[series_index]
        time_series_data = selected_series.get("data", [])

        if not time_series_data:
            return Response({"error": "No data in selected series"}, status=status.HTTP_400_BAD_REQUEST)

        data_array = np.array(time_series_data)

        # Create and run detector
        try:
            detector = get_detector(detector_config)
            result = detector.detect_batch(data_array)
        except Exception as e:
            return Response({"error": f"Detector error: {e!s}"}, status=status.HTTP_400_BAD_REQUEST)

        response_data = {
            "triggered_indices": result.triggered_indices,
            "scores": result.all_scores,
            "total_points": len(data_array),
            "anomaly_count": len(result.triggered_indices),
            "data": time_series_data,
            "labels": selected_series.get("labels", []),
            "dates": selected_series.get("dates", []),
            "series_label": selected_series.get("label", ""),
        }

        # Save AlertCheck if alert_id was provided
        if alert:
            # Calculate average value for the calculated_value field
            calculated_value = float(np.mean(data_array)) if len(data_array) > 0 else None

            # Determine state based on anomalies
            check_state = AlertState.FIRING if len(result.triggered_indices) > 0 else AlertState.NOT_FIRING

            # Extract timestamps for triggered points (for chart matching)
            # The "days" field contains date strings (for daily) or datetime strings (for hourly)
            timestamps = selected_series.get("days", [])
            triggered_dates = (
                [timestamps[i] for i in result.triggered_indices if i < len(timestamps)] if timestamps else None
            )

            check = AlertCheck.objects.create(
                alert_configuration=alert,
                calculated_value=calculated_value,
                condition=alert.condition,
                targets_notified={},
                state=check_state,
                error=None,
                anomaly_scores=result.all_scores,
                triggered_points=result.triggered_indices,
                triggered_dates=triggered_dates,
                interval=query.interval.value if query.interval else None,
            )

            response_data["saved_check_id"] = str(check.id)
            response_data["check_state"] = check_state

        return Response(response_data)


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
    insight_id: int | None = None
    insight_short_id: str | None = None
    insight_name: str | None = "Insight"
    alert_id: int | None = None
    alert_name: str | None = "Alert"


@dataclasses.dataclass(frozen=True)
class AlertSubscriptionContext(AlertConfigurationContext):
    subscriber_name: str | None = None
    subscriber_email: str | None = None


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
