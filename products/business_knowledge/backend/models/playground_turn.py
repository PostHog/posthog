from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class PlaygroundTurn(TeamScopedRootMixin, UUIDModel):
    """One question in a playground chat. `run_id` is the run that answered it."""

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
    # A null id reads the task's latest run, so a follow-up records the current run before starting another.
    run_id = models.UUIDField(null=True, blank=True)
    position = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["chat", "position"], name="bk_pg_turn_chat_pos"),
        ]

    def __str__(self) -> str:
        return f"PlaygroundTurn {self.position} ({self.chat_id})"
