from typing import Any, Dict
from rest_framework import (
    authentication,
    serializers,
    viewsets,
)

from rest_framework.permissions import IsAuthenticated
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models import ScheduledChange
from posthog.permissions import TeamMemberAccessPermission


class ScheduledChangeSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = ScheduledChange
        fields = [
            "id",
            "team_id",
            "record_id",
            "model_name",
            "payload",
            "scheduled_at",
            "executed_at",
            "failure_reason",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> ScheduledChange:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]

        return super().create(validated_data)


class ScheduledChangeViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update and delete scheduled changes.
    """

    serializer_class = ScheduledChangeSerializer
    queryset = ScheduledChange.objects.all()

    def get_queryset(self):
        queryset = ScheduledChange.objects.all()

        model_name = self.request.query_params.get("model_name")
        record_id = self.request.query_params.get("record_id")

        if model_name is not None:
            queryset = queryset.filter(model_name=model_name)
        if record_id is not None:
            queryset = queryset.filter(record_id=record_id)

        return queryset
