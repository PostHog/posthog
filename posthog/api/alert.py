from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from django.db.models import QuerySet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.alert import AlertConfiguration


class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertConfiguration
        fields = [
            "id",
            "created_at",
            "insight",
            "name",
            "notification_targets",
            "condition",
            "state",
            "notification_frequency",
            "last_notified_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "state",
            "last_notified_at",
        ]

    def create(self, validated_data: dict) -> AlertConfiguration:
        validated_data["team_id"] = self.context["team_id"]
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
