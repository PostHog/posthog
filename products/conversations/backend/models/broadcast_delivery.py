from __future__ import annotations

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .broadcast import Broadcast


class BroadcastDelivery(UUIDModel, TeamScopedRootMixin):
    """Per-channel delivery record for a `Broadcast`. One row per target Slack channel."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    # Unscoped sibling for Django framework internals (see Broadcast for rationale).
    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    broadcast = models.ForeignKey(Broadcast, on_delete=models.CASCADE, related_name="deliveries")
    slack_channel_id = models.CharField(max_length=64)
    slack_channel_name = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True, default="")
    slack_message_ts = models.CharField(max_length=64, blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_manager_name = "all_teams"
        db_table = "posthog_conversations_broadcast_delivery"
        constraints = [
            # One row per (broadcast, channel) — makes re-running send_broadcast safe.
            models.UniqueConstraint(
                fields=["broadcast", "slack_channel_id"],
                name="conv_broadcast_delivery_uniq",
            ),
        ]
        indexes = [
            # The task's hot query: pending rows for one broadcast.
            models.Index(fields=["broadcast_id", "status"], name="conv_bcast_deliv_status_idx"),
        ]

    def __str__(self) -> str:
        return f"BroadcastDelivery({self.slack_channel_id}, status={self.status})"
