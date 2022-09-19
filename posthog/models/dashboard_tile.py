from typing import List

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from posthog.models.dashboard import Dashboard
from posthog.models.insight import Insight, generate_insight_cache_key


class BaseDashboardTile(models.Model):
    layouts: models.JSONField = models.JSONField(default=dict)
    color: models.CharField = models.CharField(max_length=400, null=True, blank=True)

    class Meta:
        abstract = True


class DashboardTextTile(BaseDashboardTile):
    dashboard = models.ForeignKey("posthog.Dashboard", on_delete=models.CASCADE, related_name="text_tiles")
    body: models.CharField = models.CharField(max_length=4000, null=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    last_modified_by: models.ForeignKey = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="modified_text_tiles"
    )

    class Meta:
        indexes = [
            models.Index(fields=["dashboard"], name="query_by_dashboard_idx"),
        ]


class DashboardTile(BaseDashboardTile):
    dashboard = models.ForeignKey("posthog.Dashboard", on_delete=models.CASCADE, related_name="insight_tiles")
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE, related_name="dashboard_tiles")

    # caching for this dashboard & insight filter combination
    filters_hash: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    last_refresh: models.DateTimeField = models.DateTimeField(blank=True, null=True)
    refreshing: models.BooleanField = models.BooleanField(null=True)
    refresh_attempt: models.IntegerField = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["filters_hash"], name="query_by_filters_hash_idx")]

    def save(self, *args, **kwargs) -> None:
        has_no_filters_hash = self.filters_hash is None
        if has_no_filters_hash and self.insight.filters != {}:
            self.filters_hash = generate_insight_cache_key(self.insight, self.dashboard)

        super(DashboardTile, self).save(*args, **kwargs)


@receiver(post_save, sender=Insight)
def on_insight_saved(sender, instance: Insight, **kwargs):
    update_fields = kwargs.get("update_fields")
    if update_fields in [frozenset({"filters_hash"}), frozenset({"last_refresh"})]:
        # Don't always update the filters_hash
        return

    tile_update_candidates = DashboardTile.objects.select_related("insight", "dashboard").filter(insight=instance)
    update_filters_hashes(tile_update_candidates)


@receiver(post_save, sender=Dashboard)
def on_dashboard_saved(sender, instance: Dashboard, **kwargs):
    tile_update_candidates = DashboardTile.objects.select_related("insight", "dashboard").filter(dashboard=instance)
    update_filters_hashes(tile_update_candidates)


def update_filters_hashes(tile_update_candidates) -> None:
    tiles_to_update = []

    for tile in tile_update_candidates:
        if tile.insight.filters and tile.insight.filters != {}:
            candidate_filters_hash = generate_insight_cache_key(tile.insight, tile.dashboard)
            if tile.filters_hash != candidate_filters_hash:
                tile.filters_hash = candidate_filters_hash
                tiles_to_update.append(tile)

    if len(tiles_to_update):
        DashboardTile.objects.bulk_update(tiles_to_update, ["filters_hash"])


def get_tiles_ordered_by_position(dashboard: Dashboard, size: str = "xs") -> List[DashboardTile]:
    tiles = list(
        DashboardTile.objects.filter(dashboard=dashboard)
        .select_related("insight")
        .exclude(insight__deleted=True)
        .order_by("insight__order")
        .all()
    )
    tiles.sort(key=lambda x: x.layouts.get(size, {}).get("y", 100))
    return tiles
