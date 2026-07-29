from __future__ import annotations

from django.conf import settings
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .ticket_view import TicketView


class TicketViewFavorite(TeamScopedRootMixin, UUIDModel):
    # db_constraint=False on the hot-table FKs (team, user) so CreateModel takes no lock
    # on posthog_team / posthog_user; app-level enforcement is enough here.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    ticket_view = models.ForeignKey(TicketView, on_delete=models.CASCADE, related_name="favorites")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_conversations_ticket_view_favorites"
        unique_together = ("ticket_view", "user")
        indexes = [
            models.Index(fields=["team_id", "user"], name="conv_ticket_view_fav_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user} favorited {self.ticket_view}"
