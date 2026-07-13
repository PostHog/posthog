"""DRF views for customer-analytics announcements.

An announcement is one plain-text (Slack mrkdwn) message a CSM sends to many customer
Slack channels via the SupportHog bot. This module owns the HTTP layer: the composer's
channel picker (labeled by customer name), server-side channel validation, and the
create/list/retrieve surface. Delivery happens asynchronously in a later PR.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from slack_sdk.errors import SlackApiError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action

from products.conversations.backend.support_slack_channels import (
    SupportSlackChannelsUnavailable,
    SupportSlackNotConfigured,
    list_support_bot_channels,
)
from products.customer_analytics.backend.models import Account, Announcement, AnnouncementDelivery

logger = structlog.get_logger(__name__)

# Bound the fan-out so one announcement can't enqueue an unbounded Slack send loop.
MAX_ANNOUNCEMENT_CHANNELS = 200


class AnnouncementDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = AnnouncementDelivery
        fields = ["id", "slack_channel_id", "slack_channel_name", "status", "error", "slack_message_ts", "sent_at"]
        read_only_fields = fields
        extra_kwargs = {
            "slack_channel_id": {"help_text": "Slack channel ID the message was sent to (e.g. C0123ABCD)."},
            "slack_channel_name": {"help_text": "Slack channel display name at send time (without the leading #)."},
            "status": {"help_text": "Per-channel delivery status: pending, sent, or failed."},
            "error": {"help_text": "Slack error code when delivery to this channel failed; empty otherwise."},
            "slack_message_ts": {"help_text": "Timestamp ID of the posted Slack message, when delivery succeeded."},
            "sent_at": {"help_text": "When the message was delivered to this channel. Null until sent."},
        }


class AnnouncementChannelSerializer(serializers.Serializer):
    """A selectable Slack channel in the composer picker, labeled by customer where known."""

    id = serializers.CharField(help_text="Slack channel ID (e.g. C0123ABCD).")
    name = serializers.CharField(help_text="Slack channel display name (without the leading #).")
    is_member = serializers.BooleanField(help_text="Whether the SupportHog bot is a member of this channel.")
    customer_name = serializers.CharField(
        allow_null=True,
        help_text="Name of the customer account whose slack_channel_id points at this channel, or null if unmapped.",
    )


class AnnouncementSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    message = serializers.CharField(help_text="Message body to send, rendered as Slack mrkdwn.")
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
        model = Announcement
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
        read_only_fields = [
            "id",
            "short_id",
            "status",
            "total_channels",
            "sent_count",
            "failed_count",
            "sent_at",
            "created_at",
            "created_by",
        ]
        extra_kwargs = {
            "short_id": {"help_text": "Short human-friendly identifier for the announcement."},
            "status": {"help_text": "Overall status: pending, sending, sent, partially_failed, or failed."},
            "total_channels": {"help_text": "Number of channels this announcement targets."},
            "sent_count": {"help_text": "Number of channels the message was successfully delivered to."},
            "failed_count": {"help_text": "Number of channels delivery failed for."},
            "sent_at": {"help_text": "When delivery finished (all channels resolved). Null while pending/sending."},
            "created_at": {"help_text": "When the announcement was created."},
        }

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

    def create(self, validated_data: dict[str, Any]) -> Announcement:
        channel_ids = validated_data.pop("channels")
        view = self.context["view"]
        team = view.team

        # Security: resolve the bot's member channels server-side and reject any submitted ID
        # that isn't one of them, so a caller can't make the bot post to arbitrary Slack
        # destinations (DMs, private channels, App Home) by crafting the request body.
        try:
            allowed = {c["id"]: c for c in list_support_bot_channels(team, members_only=True)}
        except SupportSlackNotConfigured:
            raise serializers.ValidationError("The SupportHog Slack bot is not connected.")
        except (SupportSlackChannelsUnavailable, SlackApiError):
            raise serializers.ValidationError("Could not verify Slack channels right now. Please try again.")

        invalid = [cid for cid in channel_ids if cid not in allowed]
        if invalid:
            raise serializers.ValidationError(
                {"channels": "Some channels are not ones the SupportHog bot can post to."}
            )

        with transaction.atomic():
            announcement = Announcement.objects.create(
                team=team,
                message=validated_data["message"],
                created_by=self.context["request"].user,
                total_channels=len(channel_ids),
                status=Announcement.Status.PENDING,
            )
            AnnouncementDelivery.objects.bulk_create(
                [
                    AnnouncementDelivery(
                        team=team,
                        announcement=announcement,
                        slack_channel_id=cid,
                        slack_channel_name=allowed[cid]["name"],
                    )
                    for cid in channel_ids
                ]
            )
        return announcement


class AnnouncementViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "customer_analytics"
    # Unscoped at the class body (no request team context yet); safely_get_queryset scopes by team.
    queryset = Announcement.objects.unscoped().order_by("-created_at")
    serializer_class = AnnouncementSerializer
    lookup_field = "short_id"

    def safely_get_queryset(self, queryset: Any) -> Any:
        return queryset.filter(team_id=self.team_id).select_related("created_by").prefetch_related("deliveries")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        announcement = serializer.save()
        # Async delivery is wired in a follow-up PR; rows persist as pending until then.
        report_user_action(
            self.request.user,
            "customer analytics announcement created",
            {"id": str(announcement.id), "channel_count": announcement.total_channels},
            team=self.team,
        )

    @extend_schema(responses=AnnouncementChannelSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def channels(self, request: Request, **kwargs: Any) -> Response:
        """Slack channels the SupportHog bot can post to, labeled by customer account name."""
        try:
            member_channels = list_support_bot_channels(self.team, members_only=True)
        except SupportSlackNotConfigured:
            return Response([])
        except (SupportSlackChannelsUnavailable, SlackApiError):
            logger.warning("announcement_channels_unavailable", team_id=self.team_id)
            return Response([])

        name_by_channel = self._customer_names_by_channel()
        enriched = [{**c, "customer_name": name_by_channel.get(c["id"])} for c in member_channels]
        # Channels mapped to a customer sort first (by customer name); unmapped fall below by name.
        enriched.sort(key=lambda c: (c["customer_name"] is None, (c["customer_name"] or c["name"]).lower()))
        return Response(AnnouncementChannelSerializer(enriched, many=True).data)

    def _customer_names_by_channel(self) -> dict[str, str]:
        """Map Slack channel ID -> customer account name from accounts that set slack_channel_id."""
        result: dict[str, str] = {}
        for account in Account.objects.filter(_properties__has_key="slack_channel_id"):
            channel_id = account.properties.slack_channel_id
            if channel_id:
                result.setdefault(channel_id, account.name)
        return result
