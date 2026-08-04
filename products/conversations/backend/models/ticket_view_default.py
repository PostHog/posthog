from __future__ import annotations

from django.conf import settings
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .ticket_view import TicketView


class TicketViewDefault(TeamScopedRootMixin, UUIDModel):
    """The saved view Support opens on for one user in one project.

    Unique on (team, user) rather than (ticket_view, user) as TicketViewFavorite is, so Postgres
    enforces at most one default per user per project and promoting a view is a single-row upsert
    that leaves no window where the user has two defaults or none.
    """

    # db_constraint=False on the hot-table FKs (team, user) so CreateModel takes no lock
    # on posthog_team / posthog_user; app-level enforcement is enough here.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    ticket_view = models.ForeignKey(TicketView, on_delete=models.CASCADE, related_name="defaults")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_ticket_view_defaults"
        # Also the index the (team, user) lookup needs, so no separate Index is declared.
        unique_together = ("team", "user")

    def __str__(self) -> str:
        return f"{self.user} defaults to {self.ticket_view}"
