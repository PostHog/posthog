from django.db import models
from django.db.models import QuerySet

import structlog

from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel

logger = structlog.get_logger(__name__)


# KLUDGE: This is only here because we want some of our management commands
# to know this file exists and we havent figured out why it cant find models
# inside our `products` folder
#
# See https://github.com/PostHog/posthog/pull/32364
class Link(FileSystemSyncMixin, CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
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

    class Meta:
        indexes = [
            models.Index(fields=["short_link_domain", "short_code"], name="domain_short_code_idx"),
            models.Index(fields=["team_id"], name="team_id_idx"),
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

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet["Link"]:
        base_qs = cls.objects.filter(team=team)
        return cls._filter_unfiled_queryset(base_qs, team, type="link", ref_field="id")

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Links"),
            type="link",  # sync with APIScopeObject in scopes.py
            ref=str(self.id),
            name=self.short_code or "Untitled",
            href=f"/link/{self.id}",
            meta={
                "created_at": str(self.created_at),
                "created_by": self.created_by_id,
            },
            should_delete=False,
        )
