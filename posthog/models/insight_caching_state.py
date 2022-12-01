from django.db import models
from django.db.models.signals import post_save

from posthog.models.dashboard_tile import DashboardTile
from posthog.models.insight import Insight
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.signals import mutable_receiver
from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class InsightCachingState(UUIDModel):
    class Meta:
        indexes = [models.Index(fields=["cache_key"], name="filter_by_cache_key_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["insight"],
                name=f"unique_insight_for_caching_state_idx",
                condition=models.Q(("insight__isnull", False)),
            ),
            models.UniqueConstraint(
                fields=["insight", "dashboard_tile"],
                name=f"unique_dashboard_tile_idx",
                condition=models.Q(("dashboard_tile__isnull", False)),
            ),
        ]

    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)

    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE, related_name="caching_state", null=False)
    dashboard_tile = models.ForeignKey(
        "posthog.DashboardTile", on_delete=models.CASCADE, related_name="caching_state", null=True
    )
    cache_key: models.CharField = models.CharField(max_length=400, null=False, blank=False)

    target_cache_age_seconds: models.IntegerField = models.IntegerField(null=True)

    last_refresh: models.DateTimeField = models.DateTimeField(blank=True, null=True)
    last_refresh_queued_at: models.BooleanField = models.BooleanField(null=True)
    refresh_attempt: models.IntegerField = models.IntegerField(null=False, default=0)

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)


@mutable_receiver(post_save, sender=SharingConfiguration)
def sync_sharing_configuration(sender, instance: SharingConfiguration, **kwargs):
    from posthog.celery import sync_insight_caching_state

    if instance.insight_id is not None:
        sync_insight_caching_state.delay(instance.team_id, insight_id=instance.insight_id)
    elif instance.dashboard is not None:
        for tile in instance.dashboard.tiles.all():
            sync_insight_caching_state.delay(instance.team_id, dashboard_tile_id=tile.pk)


@mutable_receiver(post_save, sender=Insight)
def sync_insight(sender, instance: Insight, **kwargs):
    from posthog.celery import sync_insight_caching_state

    sync_insight_caching_state.delay(instance.team_id, insight_id=instance.pk)


@mutable_receiver(post_save, sender=DashboardTile)
def sync_dashboard_tile(sender, instance: DashboardTile, **kwargs):
    from posthog.celery import sync_insight_caching_state

    sync_insight_caching_state.delay(instance.dashboard.team_id, dashboard_tile_id=instance.pk)
