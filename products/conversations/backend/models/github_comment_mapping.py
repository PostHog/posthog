from django.db import models

from posthog.models.utils import UUIDModel

from .ticket import Ticket


class GithubCommentMapping(UUIDModel):
    github_comment_id = models.BigIntegerField(db_index=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    comment = models.ForeignKey("posthog.Comment", on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "conversations"
        db_table = "posthog_conversations_github_comment_mapping"
        constraints = [
            models.UniqueConstraint(fields=["github_comment_id", "team"], name="unique_github_comment_per_team"),
        ]

    def __str__(self) -> str:
        return f"GithubCommentMapping({self.github_comment_id} -> ticket={self.ticket_id})"
