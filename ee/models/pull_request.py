from django.db import models
from posthog.models.team.team import Team

from posthog.models.utils import UUIDModel

class PullRequest(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        OPEN = "open", "Open"
        MERGED = "merged", "Merged"
        CLOSED = "closed", "Closed"

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="pull_requests"
    )
    metadata = models.JSONField(
        help_text="The metadata of the pull request created on GitHub."
    )
    status = models.CharField(
        max_length=50,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Current status of the PR (e.g. open, merged, closed)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"PR {self.metadata['title']} on {self.metadata['repository']} for Team {self.team}"