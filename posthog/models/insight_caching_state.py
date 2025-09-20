from django.db import models
from django.db.models.signals import post_save

from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.insight import Insight
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.signals import mutable_receiver
from posthog.models.team import Team
from posthog.models.utils import UniqueConstraintByExpression, UUIDTModel
from posthog.tasks.tasks import sync_insight_caching_state


class InsightCachingState(UUIDTModel):
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


@mutable_receiver(post_save, sender=SharingConfiguration)
def sync_sharing_configuration(sender, instance: SharingConfiguration, **kwargs):
    if instance.insight is not None and not instance.insight.deleted:
        sync_insight_caching_state.delay(instance.team_id, insight_id=instance.insight_id)
    elif instance.dashboard is not None and not instance.dashboard.deleted:
        for tile in instance.dashboard.tiles.all():
            sync_insight_caching_state.delay(instance.team_id, dashboard_tile_id=tile.pk)


@mutable_receiver(post_save, sender=Insight)
def sync_insight(sender, instance: Insight, **kwargs):
    sync_insight_caching_state.delay(instance.team_id, insight_id=instance.pk)


@mutable_receiver(post_save, sender=DashboardTile)
def sync_dashboard_tile(sender, instance: DashboardTile, **kwargs):
    sync_insight_caching_state.delay(instance.dashboard.team_id, dashboard_tile_id=instance.pk)


@mutable_receiver(post_save, sender=Dashboard)
def sync_dashboard_updated(sender, instance: Dashboard, **kwargs):
    update_fields = kwargs.get("update_fields")
    if update_fields in [
        frozenset({"filters_hash"}),
        frozenset({"last_refresh"}),
        frozenset({"last_accessed_at"}),
    ]:
        return

    for tile_id in DashboardTile.objects.filter(dashboard=instance).values_list("pk", flat=True):
        sync_insight_caching_state.delay(instance.team_id, dashboard_tile_id=tile_id)
