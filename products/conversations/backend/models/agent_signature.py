from __future__ import annotations

from django.conf import settings
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

AGENT_SIGNATURE_MAX_CHARS = 1000


class AgentSignature(TeamScopedRootMixin, UUIDModel):
    # db_constraint=False on the hot-table FKs (team, user) so CreateModel takes no lock
    # on posthog_team / posthog_user; app-level enforcement is enough here.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_constraint=False, related_name="+")
    text = models.TextField(max_length=AGENT_SIGNATURE_MAX_CHARS, blank=True, default="")
    include_profile_picture = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_conversations_agent_signature"
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="conv_agent_signature_team_user_uniq"),
        ]

    def __str__(self) -> str:
        return f"Signature for {self.user} in team {self.team_id}"
