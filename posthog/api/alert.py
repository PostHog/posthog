from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from django.db.models import QuerySet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import User
from posthog.models.alert import (
    AlertConfiguration,
    AlertCheck,
    Threshold,
    AlertSubscription,
    are_alerts_supported_for_insight,
)
from posthog.schema import AlertState
from posthog.api.insight import InsightBasicSerializer

from posthog.utils import relative_date_parse
from zoneinfo import ZoneInfo
from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import Detail, log_activity, changes_between
from posthog.models.signals import model_activity_signal
from django.dispatch import receiver


class ThresholdSerializer(serializers.ModelSerializer):
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
    threshold = ThresholdSerializer()
    subscribed_users = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        many=True,
        required=True,
        write_only=True,
        allow_empty=True,
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


class AlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
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
    scope_object = "INTERNAL"
    queryset = Threshold.objects.all()
    serializer_class = ThresholdWithAlertSerializer


@receiver(model_activity_signal, sender=AlertConfiguration)
def handle_alert_configuration_change(
    sender, scope, before_update, after_update, activity, was_impersonated=False, **kwargs
):
    from posthog.utils import get_current_user_from_thread

    user = get_current_user_from_thread()
    alert_name = after_update.name or f"Alert for {after_update.insight.name}"

    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(changes=changes_between(scope, previous=before_update, current=after_update), name=alert_name),
    )
