import uuid

from django.db import models
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields
import structlog

logger = structlog.get_logger(__name__)


def generate_uuid():
    return str(uuid.uuid4())


class Link(CreatedMetaFields, UpdatedMetaFields, models.Model):
    """
    Links that redirect to a specified destination URL.
    These are used for sharing URLs across the application.
    """

    id = models.CharField(max_length=36, primary_key=True, default=generate_uuid, editable=False)
    redirect_url = models.URLField(max_length=2048)
    short_link_domain = models.CharField(max_length=255, help_text="Domain where the short link is hosted, e.g. hog.gg")
    short_code = models.CharField(
        max_length=255, help_text="The unique code/path that identifies the short link, e.g. 'abc123'"
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Optional association with a team, only for signed up customers",
    )
    description = models.TextField(null=True, blank=True)

    # created_at, created_by, updated_at are inherited from CreatedMetaFields and UpdatedMetaFields

    class Meta:
        indexes = [
            models.Index(fields=["short_link_domain", "short_code"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["short_link_domain", "short_code"], name="unique_short_link_domain_short_code"
            )
        ]

    def __str__(self):
        return f"{self.id} -> {self.redirect_url}"

    @classmethod
    def get_link(cls, team_id, link_id=None, short_link_domain=None, short_code=None):
        """
        Get a link by ID or by short_code + domain, always filtered by team.
        Returns the link instance or None if not found.
        Args:
            team_id: The team ID to filter by
            link_id: The ID of the link to get
            short_link_domain: The domain of the short link
            short_code: The short code of the link
        """
        try:
            filters = {"team_id": team_id}

            if link_id:
                filters["id"] = link_id
            elif short_link_domain and short_code:
                filters["short_link_domain"] = short_link_domain
                filters["short_code"] = short_code
            else:
                return None

            return cls.objects.get(**filters)
        except cls.DoesNotExist:
            return None
        except Exception as e:
            logger.error(
                "Failed to get link",
                team_id=team_id,
                link_id=link_id,
                short_link_domain=short_link_domain,
                short_code=short_code,
                error=str(e),
                exc_info=True,
            )
            return None

    @classmethod
    def get_links_for_team(cls, team_id, limit=100, offset=0):
        """
        Get all links for a team.
        Args:
            team_id: The team ID to get links for
            limit: Maximum number of links to return
            offset: Offset for pagination
        Returns:
            A queryset of links for the team
        """
        try:
            return cls.objects.filter(team_id=team_id).order_by("-created_at")[offset : offset + limit]
        except Exception as e:
            logger.error(
                "Failed to get links for team",
                team_id=team_id,
                error=str(e),
                exc_info=True,
            )
            return cls.objects.none()
