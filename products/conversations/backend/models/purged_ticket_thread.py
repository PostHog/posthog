from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


def ticket_thread_key(**lookup: object) -> str:
    """Stable key for an inbound thread lookup, such as a Slack channel and thread timestamp."""
    return "|".join(f"{field}={lookup[field]}" for field in sorted(lookup))


class PurgedTicketThread(TeamScopedRootMixin, UUIDModel):
    """Marks an inbound thread whose ticket was purged. It holds identifiers only, no content.

    The purge removes the ticket row, so without this marker a later message or mention in the
    same thread opens a new ticket and imports the deleted history again.
    """

    # db_constraint=False: a real FK constraint takes SHARE ROW EXCLUSIVE on posthog_team while
    # migrating, stalling writes under traffic.
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    thread_key = models.CharField(max_length=1024)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_purged_ticket_thread"
        constraints = [
            models.UniqueConstraint(fields=["team", "thread_key"], name="unique_purged_thread_per_team"),
        ]

    def __str__(self) -> str:
        return f"PurgedTicketThread({self.team_id}:{self.thread_key})"
