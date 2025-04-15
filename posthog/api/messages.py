from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
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
            "type",
            "kind",
        ]
        read_only_fields = fields


class MessageViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "hog_function"
    permission_classes = [IsAuthenticated]

    serializer_class = MessageSerializer
    queryset = HogFunction.objects.all()

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
        queryset = self.safely_get_queryset(self.get_queryset()).filter(
            Q(type__in=["broadcast"]) | Q(kind__in=["messaging_campaign"])
        )
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request: Request, *args, **kwargs):
        return Response(self.get_serializer(self.get_object()).data)
