from __future__ import annotations

from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models.user import User

from products.customer_analytics.backend.facade import api
from products.customer_analytics.backend.facade.contracts import (
    AnnouncementTemplateValidationError,
    AnnouncementTemplateView,
)
from products.customer_analytics.backend.presentation.views.views import _FacadePaginationMixin


class AnnouncementTemplateSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(
        max_length=255, help_text="Unique, human-friendly name for the template (unique per team)."
    )
    message = serializers.CharField(
        help_text="Reusable message body, rendered as Slack mrkdwn when the announcement is sent."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the template was created.")
    updated_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the template was last edited."
    )
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        dataclass = AnnouncementTemplateView
        ref_name = "AnnouncementTemplate"
        fields = ["id", "name", "message", "created_at", "updated_at", "created_by"]

    def validate_name(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError("Name cannot be empty.")
        return stripped

    def validate_message(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Message cannot be empty.")
        return value


class AnnouncementTemplateViewSet(
    TeamAndOrgViewSetMixin,
    _FacadePaginationMixin,
    viewsets.ReadOnlyModelViewSet,
):
    """Team-shared library of reusable announcement message bodies.

    Templates store only the message. Recipients are still chosen fresh per send in the
    announcement composer. All data is reached through the facade; no product models are
    imported here.
    """

    scope_object = "customer_analytics"
    serializer_class = AnnouncementTemplateSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_announcement_templates(self.team_id, offset=offset, limit=limit),
            AnnouncementTemplateSerializer,
        )

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        template = api.get_announcement_template(self.team_id, self.kwargs["pk"])
        if template is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AnnouncementTemplateSerializer(instance=template).data)

    @extend_schema(request=AnnouncementTemplateSerializer, responses=AnnouncementTemplateSerializer)
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AnnouncementTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            template = api.create_announcement_template(
                team_id=self.team_id,
                user=cast(User, request.user),
                name=data.name,
                message=data.message,
            )
        except AnnouncementTemplateValidationError as e:
            raise serializers.ValidationError(e.detail)
        report_user_action(
            request.user,
            "customer analytics announcement template created",
            {"id": str(template.id)},
            team=self.team,
            request=request,
        )
        return Response(AnnouncementTemplateSerializer(instance=template).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=AnnouncementTemplateSerializer, responses=AnnouncementTemplateSerializer)
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AnnouncementTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            template = api.update_announcement_template(
                team_id=self.team_id,
                template_id=self.kwargs["pk"],
                name=data.name,
                message=data.message,
            )
        except AnnouncementTemplateValidationError as e:
            raise serializers.ValidationError(e.detail)
        if template is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AnnouncementTemplateSerializer(instance=template).data)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not api.delete_announcement_template(self.team_id, self.kwargs["pk"]):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
