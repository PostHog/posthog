from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class PlaygroundTurn(TeamScopedRootMixin, UUIDModel):
    """One question in a playground chat, pointing at a sandbox task."""

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        # Creating a real FK takes SHARE ROW EXCLUSIVE on posthog_team.
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    chat = models.ForeignKey("business_knowledge.PlaygroundChat", on_delete=models.CASCADE, related_name="turns")
    question = models.TextField()
    task_id = models.UUIDField()
    position = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["chat", "position"], name="bk_pg_turn_chat_pos"),
            models.UniqueConstraint(fields=["task_id"], name="bk_pg_turn_task_id"),
        ]

    def __str__(self) -> str:
        return f"PlaygroundTurn {self.position} ({self.chat_id})"
