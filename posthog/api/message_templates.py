from typing import Any

from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from posthog.models import MessageTemplate
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.forbid_destroy_model import ForbidDestroyModel


class MessageTemplateSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = MessageTemplate
        fields = [
            "id",
            "name",
            "description",
            "created_at",
            "updated_at",
            "content",
            "created_by",
            "type",
        ]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]

    def create(self, validated_data: Any) -> Any:
        request = self.context["request"]
        team_id = self.context["team_id"]

        instance = MessageTemplate.objects.create(**validated_data, team_id=team_id, created_by=request.user)
        return instance


class MessageTemplateViewSet(
    TeamAndOrgViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    serializer_class = MessageTemplateSerializer
    queryset = MessageTemplate.objects.all()

    def safely_get_queryset(self, queryset):
        return (
            queryset.filter(
                team_id=self.team_id,
                deleted=False,
            )
            .select_related("created_by")
            .order_by("-created_at")
        )
