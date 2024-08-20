from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from django.db.models import QuerySet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import User
from posthog.models.alert import AlertConfiguration, AlertCheck, Threshold, AlertSubscription


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
        try:
            instance.clean()
            return data
        except ValueError as e:
            raise ValidationError(str(e))


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


class AlertSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    checks = AlertCheckSerializer(many=True, read_only=True)
    threshold = ThresholdSerializer()
    subscribed_users = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True), many=True, required=True, write_only=True
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
            "checks",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "state",
            "last_notified_at",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["subscribed_users"] = UserBasicSerializer(instance.subscribed_users.all(), many=True, read_only=True).data
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
        threshold_data = validated_data.pop("threshold", None)
        if threshold_data is not None:
            if threshold_data == {}:
                instance.threshold = None
            elif instance.threshold:
                threshold_instance = instance.threshold
                for key, value in threshold_data.items():
                    setattr(threshold_instance, key, value)
                threshold_instance.save()
            else:
                threshold_instance = self.add_threshold(threshold_data, validated_data)
                validated_data["threshold"] = threshold_instance

        subscribed_users = validated_data.pop("subscribed_users", None)
        if subscribed_users is not None:
            AlertSubscription.objects.filter(alert_configuration=instance).exclude(user__in=subscribed_users).delete()
            for user in subscribed_users:
                AlertSubscription.objects.get_or_create(
                    user=user, alert_configuration=instance, defaults={"created_by": self.context["request"].user}
                )

        return super().update(instance, validated_data)

    def validate_subscribed_users(self, value):
        for user in value:
            if not user.teams.filter(pk=self.context["team_id"]).exists():
                raise ValidationError("User does not belong to the same organization as the alert's team.")
        return value

    def validate(self, attrs):
        if attrs.get("insight") and attrs["insight"].team.id != self.context["team_id"]:
            raise ValidationError({"insight": ["This insight does not belong to your team."]})

        if attrs.get("enabled") is not False and (
            AlertConfiguration.objects.filter(team_id=self.context["team_id"], enabled=True).count()
            >= AlertConfiguration.ALERTS_PER_TEAM
        ):
            raise ValidationError(
                {"alert": [f"Your team has reached the limit of {AlertConfiguration.ALERTS_PER_TEAM} enabled alerts."]}
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


class ThresholdWithAlertSerializer(ThresholdSerializer):
    alerts = AlertSerializer(many=True, read_only=True, source="alertconfiguration_set")

    class Meta(ThresholdSerializer.Meta):
        fields = [*ThresholdSerializer.Meta.fields, "alerts"]
        read_only_fields = [*ThresholdSerializer.Meta.read_only_fields, "alerts"]


class ThresholdViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    queryset = Threshold.objects.all()
    serializer_class = ThresholdWithAlertSerializer
