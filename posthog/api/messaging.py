from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from posthog.models import HogFunction
from posthog.api.routing import TeamAndOrgViewSetMixin
from typing import Any
from django.db.models import Q
from posthog.api.shared import UserBasicSerializer


class MessageSerializer(serializers.ModelSerializer):
    content = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(read_only=True)

    def get_content(self, obj: HogFunction) -> dict[str, Any]:
        return obj.inputs.get("email", {})

    class Meta:
        model = HogFunction
        fields = [
            "id",
            "name",
            "description",
            "created_at",
            "content",
            "template_id",
            "created_by",
        ]
        read_only_fields = fields


class MessagingViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "message"
    permission_classes = [IsAuthenticated]

    serializer_class = MessageSerializer
    queryset = HogFunction.objects.all()

    def safely_get_queryset(self, queryset):
        return (
            queryset.filter(
                team_id=self.team_id,
                deleted=False,
            )
            .filter(Q(type__in=["broadcast"]) | Q(kind__in=["messaging_campaign"]))
            .select_related("created_by")
            .order_by("-created_at")
        )
