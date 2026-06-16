from __future__ import annotations

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel
from posthog.utils import generate_short_id


class Broadcast(CreatedMetaFields, UpdatedMetaFields, UUIDModel, TeamScopedRootMixin):
    """A single message an agent sends to many Slack channels via the SupportHog bot.

    The message + selected channels are persisted up front; actual delivery happens
    asynchronously (one `BroadcastDelivery` row per channel), so partial Slack failures
    are isolated and visible rather than silently lost.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        PARTIALLY_FAILED = "partially_failed", "Partially failed"
        FAILED = "failed", "Failed"

    # `objects` (TeamScopedManager) inherited from TeamScopedRootMixin is fail-closed for
    # explicit user code. `all_teams` is the unscoped sibling for Django framework internals
    # (related-object access, prefetch_related, DRF class-body querysets); Meta's
    # default_manager_name routes _default_manager/_base_manager there. Same pattern as
    # products/signals and products/streamlit_apps.
    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    # Denormalized counts so the history list renders without per-row aggregation.
    total_channels = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_manager_name = "all_teams"
        db_table = "posthog_conversations_broadcast"
        indexes = [
            models.Index(fields=["team_id", "-created_at"], name="conv_broadcast_team_idx"),
        ]

    def __str__(self) -> str:
        return f"Broadcast({self.short_id}, status={self.status})"
