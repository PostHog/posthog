from django.db import models

from posthog.models.team import Team
from posthog.models.utils import UniqueConstraintByExpression, UUIDModel


class InsightCachingState(UUIDModel):
    class Meta:
        indexes = [models.Index(fields=["cache_key"], name="filter_by_cache_key_idx")]
        constraints = [
            UniqueConstraintByExpression(
                name="unique_insight_tile_idx",
                expression="(insight_id, coalesce(dashboard_tile_id, -1))",
            )
        ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE)

    insight = models.ForeignKey(
        "posthog.Insight",
        on_delete=models.CASCADE,
        related_name="caching_states",
        null=False,
    )
    dashboard_tile = models.ForeignKey(
        "posthog.DashboardTile",
        on_delete=models.CASCADE,
        related_name="caching_states",
        null=True,
    )
    cache_key = models.CharField(max_length=400, null=False, blank=False)

    target_cache_age_seconds = models.IntegerField(null=True)

    last_refresh = models.DateTimeField(blank=True, null=True)
    last_refresh_queued_at = models.DateTimeField(blank=True, null=True)
    refresh_attempt = models.IntegerField(null=False, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
