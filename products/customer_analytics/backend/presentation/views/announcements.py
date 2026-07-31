from __future__ import annotations

from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models.user import User

from products.customer_analytics.backend.facade import api
from products.customer_analytics.backend.facade.constants import MAX_ANNOUNCEMENT_CHANNELS
from products.customer_analytics.backend.facade.contracts import (
    AnnouncementDeliveryView,
    AnnouncementValidationError,
    AnnouncementView,
)
from products.customer_analytics.backend.presentation.views.views import _FacadePaginationMixin

# Duplicated from the model TextChoices so this module imports no product models;
# ENUM_NAME_OVERRIDES matches the generated enums against these by value.
_ANNOUNCEMENT_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("sending", "Sending"),
    ("sent", "Sent"),
    ("partially_failed", "Partially failed"),
    ("failed", "Failed"),
]

_DELIVERY_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("sent", "Sent"),
    ("failed", "Failed"),
]


class AnnouncementDeliverySerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True)
    slack_channel_id = serializers.CharField(
        read_only=True, help_text="Slack channel ID the message was sent to (e.g. C0123ABCD)."
    )
    slack_channel_name = serializers.CharField(
        read_only=True, help_text="Slack channel display name at send time (without the leading #)."
    )
    status = serializers.ChoiceField(
        read_only=True,
        choices=_DELIVERY_STATUS_CHOICES,
        help_text="Per-channel delivery status: pending, sent, or failed.",
    )
    error = serializers.CharField(
        read_only=True, help_text="Slack error code when delivery to this channel failed; empty otherwise."
    )
    slack_message_ts = serializers.CharField(
        read_only=True, help_text="Timestamp ID of the posted Slack message, when delivery succeeded."
    )
    sent_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the message was delivered to this channel. Null until sent."
    )

    class Meta:
        dataclass = AnnouncementDeliveryView
        ref_name = "AnnouncementDelivery"
        fields = ["id", "slack_channel_id", "slack_channel_name", "status", "error", "slack_message_ts", "sent_at"]


class AnnouncementChannelSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Slack channel ID (e.g. C0123ABCD).")
    name = serializers.CharField(help_text="Slack channel display name (without the leading #).")
    is_member = serializers.BooleanField(help_text="Whether the SupportHog bot is a member of this channel.")
    customer_name = serializers.CharField(
        allow_null=True,
        help_text="Name of the customer account whose slack_channel_id points at this channel, or null if unmapped.",
    )


class AnnouncementSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True)
    short_id = serializers.CharField(read_only=True, help_text="Short human-friendly identifier for the announcement.")
    message = serializers.CharField(help_text="Message body to send, rendered as Slack mrkdwn.")
    status = serializers.ChoiceField(
        read_only=True,
        choices=_ANNOUNCEMENT_STATUS_CHOICES,
        help_text="Overall status: pending, sending, sent, partially_failed, or failed.",
    )
    total_channels = serializers.IntegerField(read_only=True, help_text="Number of channels this announcement targets.")
    sent_count = serializers.IntegerField(
        read_only=True, help_text="Number of channels the message was successfully delivered to."
    )
    failed_count = serializers.IntegerField(read_only=True, help_text="Number of channels delivery failed for.")
    sent_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When delivery finished (all channels resolved). Null while pending/sending.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the announcement was created.")
    created_by = UserBasicSerializer(read_only=True)
    deliveries = AnnouncementDeliverySerializer(
        many=True, read_only=True, help_text="Per-channel delivery rows, one per selected Slack channel."
    )
    channels = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        help_text="Slack channel IDs to send to. Each must be a channel the SupportHog bot is a member of; "
        "names are resolved server-side.",
    )

    class Meta:
        dataclass = AnnouncementView
        ref_name = "Announcement"
        fields = [
            "id",
            "short_id",
            "message",
            "status",
            "total_channels",
            "sent_count",
            "failed_count",
            "sent_at",
            "created_at",
            "created_by",
            "deliveries",
            "channels",
        ]

    def validate_message(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Message cannot be empty.")
        return value

    def validate_channels(self, value: list[str]) -> list[str]:
        deduped = list(dict.fromkeys(value))
        if not deduped:
            raise serializers.ValidationError("Select at least one channel.")
        if len(deduped) > MAX_ANNOUNCEMENT_CHANNELS:
            raise serializers.ValidationError(
                f"An announcement can target at most {MAX_ANNOUNCEMENT_CHANNELS} channels."
            )
        return deduped


class AnnouncementViewSet(
    TeamAndOrgViewSetMixin,
    _FacadePaginationMixin,
    mixins.CreateModelMixin,
    viewsets.ReadOnlyModelViewSet,
):
    scope_object = "customer_analytics"
    serializer_class = AnnouncementSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only
    lookup_field = "short_id"

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_announcements(self.team_id, offset=offset, limit=limit),
            AnnouncementSerializer,
        )

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        announcement = api.get_announcement(self.team_id, self.kwargs["short_id"])
        if announcement is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AnnouncementSerializer(instance=announcement).data)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AnnouncementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            announcement = api.create_announcement(
                team_id=self.team_id,
                user=cast(User, request.user),
                message=data.message,
                channels=data.channels,
            )
        except AnnouncementValidationError as e:
            raise serializers.ValidationError(e.detail)
        report_user_action(
            request.user,
            "customer analytics announcement created",
            {"id": str(announcement.id), "channel_count": announcement.total_channels},
            team=self.team,
        )
        return Response(AnnouncementSerializer(instance=announcement).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses=AnnouncementChannelSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def channels(self, request: Request, **kwargs: Any) -> Response:
        """Slack channels the SupportHog bot can post to, labeled by customer account name."""
        member_channels = api.list_announcement_channels(self.team_id)
        return Response(AnnouncementChannelSerializer(member_channels, many=True).data)
