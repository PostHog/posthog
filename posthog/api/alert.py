from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from django.db.models import QuerySet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.alert import AlertConfiguration, AlertCheck


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


class AlertSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    checks = AlertCheckSerializer(many=True, read_only=True)

    class Meta:
        model = AlertConfiguration
        fields = [
            "id",
            "created_by",
            "created_at",
            "insight",
            "name",
            "notification_targets",
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

    def create(self, validated_data: dict) -> AlertConfiguration:
        request = self.context["request"]
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = request.user
        instance: AlertConfiguration = super().create(validated_data)
        return instance

    def validate(self, attrs):
        if attrs.get("insight") and attrs["insight"].team.id != self.context["team_id"]:
            raise ValidationError({"insight": ["This insight does not belong to your team."]})
        return attrs


class AlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = AlertConfiguration.objects.all()
    serializer_class = AlertSerializer

    def safely_get_queryset(self, queryset) -> QuerySet:
        filters = self.request.query_params
        if "insight" in filters:
            queryset = queryset.filter(insight_id=filters["insight"])
        return queryset

    def retrieve(self, request, *args, **kwargs):
        instance: AlertConfiguration = self.get_object()
        instance.checks = instance.alertcheck_set.all().order_by("-created_at")[:5]
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
