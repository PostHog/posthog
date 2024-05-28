from typing import Any

from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.alert import Alert


class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = [
            "id",
            "insight",
            "name",
            "target_value",
            "anomaly_condition",
        ]
        read_only_fields = ["id"]

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Alert:
        validated_data["team_id"] = self.context["team_id"]
        instance: Alert = super().create(validated_data)
        return instance

    def validate(self, attrs):
        if attrs.get("insight") and attrs["insight"].team.id != self.context["team_id"]:
            raise ValidationError({"insight": ["This insight does not belong to your team."]})
        return attrs


class AlertViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "alert"
    queryset = Alert.objects.all()
    serializer_class = AlertSerializer
