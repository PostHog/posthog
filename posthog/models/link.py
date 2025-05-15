import structlog

from django.db import models
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

logger = structlog.get_logger(__name__)


class Link(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """
    Links that redirect to a specified destination URL.
    These are used for sharing URLs across the application.
    """

    redirect_url = models.URLField(max_length=2048)
    short_link_domain = models.CharField(max_length=255, help_text="Domain where the short link is hosted, e.g. hog.gg")
    short_code = models.CharField(
        max_length=255, help_text="The unique code/path that identifies the short link, e.g. 'abc123'"
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        help_text="Team that owns this link",
    )
    description = models.TextField(null=True, blank=True)

    # created_at, created_by, updated_at are inherited from CreatedMetaFields and UpdatedMetaFields

    class Meta:
        indexes = [
            models.Index(fields=["short_link_domain", "short_code"]),
            models.Index(fields=["team_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["short_link_domain", "short_code"], name="unique_short_link_domain_short_code"
            )
        ]

    def __str__(self):
        return f"{self.id} -> {self.redirect_url}"

    @classmethod
    def get_links_for_team(cls, team_id, limit=100, offset=0):
        """
        Get all links for a team with pagination.
        Args:
            team_id: The team ID to get links for
            limit: Maximum number of links to return
            offset: Offset for pagination
        Returns:
            A queryset of links for the team
        """
        return cls.objects.filter(team_id=team_id).order_by("-created_at")[offset : offset + limit]
