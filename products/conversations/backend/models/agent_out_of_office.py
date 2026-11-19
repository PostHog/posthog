from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class AgentOutOfOffice(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    """A support agent who is out of office. The row exists while they are away and is deleted when they are back."""

    activity_logging_on_delete = True

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_agent_out_of_office"
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="conv_agent_ooo_team_user_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} out of office"
