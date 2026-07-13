from __future__ import annotations

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .announcement import Announcement


class AnnouncementDelivery(TeamScopedRootMixin, UUIDModel):
    """Per-channel delivery record for an `Announcement`. One row per target Slack channel."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    # Unscoped sibling for Django framework internals (see Announcement for rationale).
    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="deliveries")
    slack_channel_id = models.CharField(max_length=64)
    slack_channel_name = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True, default="")
    slack_message_ts = models.CharField(max_length=64, blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TeamScopedRootMixin.Meta):
        default_manager_name = "all_teams"
        constraints = [
            # One row per (announcement, channel) — makes re-running send_announcement safe.
            models.UniqueConstraint(
                fields=["announcement", "slack_channel_id"],
                name="ca_announcement_delivery_uniq",
            ),
        ]
        indexes = [
            # The send task's hot query: pending rows for one announcement.
            models.Index(fields=["announcement_id", "status"], name="ca_ann_deliv_status_idx"),
        ]

    def __str__(self) -> str:
        return f"AnnouncementDelivery({self.slack_channel_id}, status={self.status})"
