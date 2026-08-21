from django.db import models
from django.db.models.functions import Lower

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class TicketGithubLinkType(models.TextChoices):
    ISSUE = "issue", "Issue"
    PULL_REQUEST = "pull_request", "Pull request"


class TicketGithubLinkState(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"
    MERGED = "merged", "Merged"


class TicketGithubLink(TeamScopedRootMixin, UUIDModel):
    """A GitHub issue or pull request a teammate attached to a ticket for cross-reference.

    Distinct from Ticket.github_repo/github_issue_number, which identify the issue a
    GitHub-channel ticket was created from and drive reply routing.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    ticket = models.ForeignKey("conversations.Ticket", on_delete=models.CASCADE, related_name="github_links")
    repo = models.CharField(max_length=256)  # owner/repo
    number = models.PositiveIntegerField()
    link_type = models.CharField(max_length=16, choices=TicketGithubLinkType.choices)
    # Filled from the GitHub API when a GitHub integration in the project can see the repo; null otherwise.
    title = models.CharField(max_length=512, null=True, blank=True)
    link_state = models.CharField(max_length=16, choices=TicketGithubLinkState.choices, null=True, blank=True)
    metadata_synced_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_conversations_ticket_github_link"
        constraints = [
            # GitHub repository names are case-insensitive, so PostHog/posthog#1 and posthog/posthog#1 are one link.
            models.UniqueConstraint(Lower("repo"), "ticket", "number", name="unique_github_link_per_ticket"),
        ]

    @property
    def url(self) -> str:
        path = "pull" if self.link_type == TicketGithubLinkType.PULL_REQUEST else "issues"
        return f"https://github.com/{self.repo}/{path}/{self.number}"

    def __str__(self) -> str:
        return f"TicketGithubLink({self.repo}#{self.number} -> ticket={self.ticket_id})"
