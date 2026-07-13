from __future__ import annotations

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel
from posthog.utils import generate_short_id


class Announcement(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """A single message a CSM sends to many customer Slack channels via the SupportHog bot.

    The message + selected channels are persisted up front; actual delivery happens
    asynchronously (one `AnnouncementDelivery` row per channel), so partial Slack failures
    are isolated and visible rather than silently lost.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        PARTIALLY_FAILED = "partially_failed", "Partially failed"
        FAILED = "failed", "Failed"

    # `objects` (TeamScopedManager) from TeamScopedRootMixin is fail-closed for explicit user
    # code. `all_teams` is the unscoped sibling for Django framework internals (related-object
    # access, prefetch_related, DRF class-body querysets); Meta.default_manager_name routes
    # _default_manager/_base_manager there. Same pattern as products/dashboards DashboardWidget.
    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    # Redeclared from CreatedMetaFields to drop the FK db_constraint (hot-table lock hazard);
    # the real constraint is added NOT VALID in a follow-up migration.
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )

    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    # Denormalized counts so the history list renders without per-row aggregation.
    total_channels = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta(TeamScopedRootMixin.Meta):
        default_manager_name = "all_teams"
        indexes = [
            models.Index(fields=["team_id", "-created_at"], name="ca_announcement_team_idx"),
        ]

    def __str__(self) -> str:
        return f"Announcement({self.short_id}, status={self.status})"
