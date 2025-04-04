from rest_framework import serializers, viewsets
from posthog.models import HogFunction
from posthog.api.routing import TeamAndOrgViewSetMixin
from typing import Any


class MessageSerializer(serializers.ModelSerializer):
    content = serializers.SerializerMethodField()

    def get_content(self, obj: HogFunction) -> dict[str, Any]:
        return obj.inputs.get("email", {})

    class Meta:
        model = HogFunction
        fields = [
            "id",
            "name",
            "description",
            "created_at",
            "updated_at",
            "content",
        ]
        read_only_fields = fields


class MessageViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = MessageSerializer
    queryset = HogFunction.objects.none()  # Required for DRF

    def safely_get_queryset(self):
        return HogFunction.objects.filter(
            team_id=self.team_id, type__in=["broadcast"], kind__in=["messaging_campaign"], deleted=False
        ).order_by("-created_at")
