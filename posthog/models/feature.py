from django.db import models
from posthog.models.utils import UUIDModel, sane_repr


class Feature(UUIDModel):
    class Status(models.TextChoices):
        CONCEPT = "concept", "concept"
        ALPHA = "alpha", "alpha"
        BETA = "beta", "beta"
        GENERAL_AVAILABILITY = "general-availability", "general availability"

    team: models.ForeignKey = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, related_name="features", related_query_name="feature"
    )
    feature_flag: models.ForeignKey = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="features",
        related_query_name="feature",
    )
    status: models.CharField = models.CharField(max_length=40, choices=Status.choices)
    name: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    description: models.TextField = models.TextField()
    image_url: models.URLField = models.URLField(max_length=800, null=True, blank=True)
    documentation_url: models.URLField = models.URLField(max_length=800, null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name

    __repr__ = sane_repr("id", "name", "team_id", "status")
