from django.db import models
from posthog.models.utils import UUIDModel, sane_repr


class EarlyAccessFeature(UUIDModel):
    class Stage(models.TextChoices):
        DRAFT = "draft", "draft"
        CONCEPT = "concept", "concept"
        ALPHA = "alpha", "alpha"
        BETA = "beta", "beta"
        GENERAL_AVAILABILITY = "general-availability", "general availability"
        ARCHIVED = "archived", "archived"

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="features",
        related_query_name="feature",
    )
    feature_flag = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="features",
        related_query_name="feature",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    stage = models.CharField(max_length=40, choices=Stage.choices)
    documentation_url = models.URLField(max_length=800, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name

    __repr__ = sane_repr("id", "name", "team_id", "stage")
