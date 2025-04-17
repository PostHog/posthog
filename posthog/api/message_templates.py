from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from posthog.models import MessageTemplate
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer


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
            "deleted",
        ]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]


class MessageTemplateViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "message_template"
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

    def list(self, request: Request, *args, **kwargs):
        queryset = self.safely_get_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
