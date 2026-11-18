from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class PlaygroundChat(TeamScopedRootMixin, UUIDModel):
    """A playground thread owned by one person. The chat is one sandbox task. Each question is a run on that task."""

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        # Creating a real FK takes SHARE ROW EXCLUSIVE on posthog_team.
        db_constraint=False,
        # (team, created_by, -created_at) already leads with team_id.
        db_index=False,
        related_name="+",
    )
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="+",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    # Null until the first question. Later questions resume this task.
    task_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "created_by", "-created_at"], name="bk_pg_chat_owner_created"),
        ]

    def __str__(self) -> str:
        return self.title or f"PlaygroundChat {self.id}"
