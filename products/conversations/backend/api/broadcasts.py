from typing import Any

from django.db import transaction

from rest_framework import mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action

from products.conversations.backend.models import Broadcast, BroadcastDelivery
from products.conversations.backend.tasks import send_broadcast

# Bound the fan-out so one broadcast can't enqueue an unbounded Slack send loop.
MAX_BROADCAST_CHANNELS = 200


class BroadcastDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = BroadcastDelivery
        fields = [
            "id",
            "slack_channel_id",
            "slack_channel_name",
            "status",
            "error",
            "slack_message_ts",
            "sent_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "slack_channel_id": {"help_text": "Slack channel ID the message was sent to (e.g. C0123ABCD)."},
            "slack_channel_name": {"help_text": "Slack channel display name at send time (without the leading #)."},
            "status": {"help_text": "Per-channel delivery status: pending, sent, or failed."},
            "error": {"help_text": "Slack error code when delivery to this channel failed; empty otherwise."},
            "slack_message_ts": {"help_text": "Timestamp ID of the posted Slack message, when delivery succeeded."},
            "sent_at": {"help_text": "When the message was delivered to this channel. Null until sent."},
        }


class BroadcastChannelInputSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Slack channel ID to broadcast to (e.g. C0123ABCD).")
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Slack channel display name (without the leading #), stored on the delivery row for display.",
    )


class BroadcastSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    message = serializers.CharField(help_text="Message body to broadcast, rendered as Slack mrkdwn.")
    deliveries = BroadcastDeliverySerializer(
        many=True,
        read_only=True,
        help_text="Per-channel delivery rows, one per selected Slack channel.",
    )
    channels = BroadcastChannelInputSerializer(
        many=True,
        write_only=True,
        help_text="Channels to broadcast to. Each must be a channel the SupportHog bot is a member of.",
    )

    class Meta:
        model = Broadcast
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
            "short_id": {"help_text": "Short human-friendly identifier for the broadcast."},
            "status": {
                "help_text": "Overall delivery status: pending, sending, sent, partially_failed, or failed.",
            },
            "total_channels": {"help_text": "Number of channels this broadcast targets."},
            "sent_count": {"help_text": "Number of channels the message was successfully delivered to."},
            "failed_count": {"help_text": "Number of channels delivery failed for."},
            "sent_at": {"help_text": "When delivery finished (all channels resolved). Null while pending/sending."},
            "created_at": {"help_text": "When the broadcast was created."},
        }

    def validate_message(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Message cannot be empty.")
        return value

    def validate_channels(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not value:
            raise serializers.ValidationError("Select at least one channel.")
        deduped: dict[str, dict[str, Any]] = {}
        for channel in value:
            deduped.setdefault(channel["id"], channel)
        if len(deduped) > MAX_BROADCAST_CHANNELS:
            raise serializers.ValidationError(f"A broadcast can target at most {MAX_BROADCAST_CHANNELS} channels.")
        return list(deduped.values())

    def create(self, validated_data: dict[str, Any]) -> Broadcast:
        channels = validated_data.pop("channels")
        team_id = self.context["team_id"]
        with transaction.atomic():
            broadcast = Broadcast.objects.create(
                team_id=team_id,
                message=validated_data["message"],
                created_by=self.context["request"].user,
                total_channels=len(channels),
                status=Broadcast.Status.PENDING,
            )
            BroadcastDelivery.objects.bulk_create(
                [
                    BroadcastDelivery(
                        team_id=broadcast.team_id,
                        broadcast=broadcast,
                        slack_channel_id=channel["id"],
                        slack_channel_name=channel.get("name", ""),
                    )
                    for channel in channels
                ]
            )
        return broadcast


class BroadcastViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "conversation"
    queryset = Broadcast.objects.unscoped().order_by("-created_at")
    serializer_class = BroadcastSerializer
    lookup_field = "short_id"

    def safely_get_queryset(self, queryset: Any) -> Any:
        return queryset.filter(team_id=self.team_id).select_related("created_by").prefetch_related("deliveries")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        broadcast = serializer.save()
        # Side effect must not run if the create rolls back, and CLAUDE.md forbids
        # enqueueing Celery inside the atomic block — dispatch after commit.
        transaction.on_commit(lambda: send_broadcast.delay(str(broadcast.id), self.team_id))
        report_user_action(
            self.request.user,
            "support broadcast created",
            {"id": str(broadcast.id), "channel_count": broadcast.total_channels},
            team=self.team,
            request=self.request,
        )
