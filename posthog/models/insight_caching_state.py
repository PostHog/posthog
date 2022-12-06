from django.db import models

from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class InsightCachingState(UUIDModel):
    class Meta:
        indexes = [models.Index(fields=["cache_key"], name="filter_by_cache_key_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["insight"],
                name=f"unique_insight_for_caching_state_idx",
                condition=models.Q(("dashboard_tile__isnull", True)),
            ),
            models.UniqueConstraint(
                fields=["insight", "dashboard_tile"],
                name=f"unique_dashboard_tile_idx",
                condition=models.Q(("dashboard_tile__isnull", False)),
            ),
        ]

    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)

    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE, related_name="caching_states", null=False)
    dashboard_tile = models.ForeignKey(
        "posthog.DashboardTile", on_delete=models.CASCADE, related_name="caching_states", null=True
    )
    cache_key: models.CharField = models.CharField(max_length=400, null=False, blank=False)

    target_cache_age_seconds: models.IntegerField = models.IntegerField(null=True)

    last_refresh: models.DateTimeField = models.DateTimeField(blank=True, null=True)
    last_refresh_queued_at: models.DateTimeField = models.DateTimeField(blank=True, null=True)
    refresh_attempt: models.IntegerField = models.IntegerField(null=False, default=0)

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
