from django.core.validators import URLValidator
from django.db import models

from posthog.models.utils import UUIDModel


class OrganizationExternalProjectLink(UUIDModel):
    """A link to a project on another PostHog instance, shown in this organization's project switcher.

    Staff set these in the Django admin for customers who keep an organization in each cloud region.
    """

    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="external_project_links",
        # The FK constraint would lock the hot organization table during migration; the ORM
        # cascade still removes these rows when the organization is deleted.
        db_constraint=False,
    )
    name = models.CharField(max_length=200, help_text="Shown in the project switcher, for example 'Acme (EU)'.")
    url = models.URLField(
        max_length=2000,
        validators=[URLValidator(schemes=["https"])],
        help_text="Full https URL of the project, for example https://eu.posthog.com/project/123.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
