from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDTModel


class UserFacetSettings(UUIDTModel, TeamScopedRootMixin):
    """Stores a user's custom facets (pinned log/span attributes) for a product within a team."""

    class Product(models.TextChoices):
        LOGS = "logs"
        TRACING = "tracing"

    user = models.ForeignKey(
        "User",
        on_delete=models.CASCADE,
        related_name="facet_settings",
        db_constraint=False,
    )
    team = models.ForeignKey("Team", on_delete=models.CASCADE, db_constraint=False)
    product = models.CharField(max_length=32, choices=Product.choices)
    custom_facets = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user", "product"],
                name="posthog_unique_user_facet_settings",
            )
        ]
