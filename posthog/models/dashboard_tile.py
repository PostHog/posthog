from typing import Optional

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.models.dashboard import Dashboard
from posthog.models.filters.utils import get_filter
from posthog.models.insight import Insight
from posthog.utils import generate_cache_key


def generate_insight_cache_key(insight: Insight, dashboard: Optional[Dashboard]) -> str:
    dashboard_insight_filter = get_filter(data=insight.dashboard_filters(dashboard=dashboard), team=insight.team)
    candidate_filters_hash = generate_cache_key("{}_{}".format(dashboard_insight_filter.toJSON(), insight.team_id))
    return candidate_filters_hash


class DashboardTile(models.Model):
    # Relations
    dashboard = models.ForeignKey("posthog.Dashboard", on_delete=models.CASCADE)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)

    # Dashboard layout and style
    layouts: models.JSONField = models.JSONField(default=dict)
    color: models.CharField = models.CharField(max_length=400, null=True, blank=True)

    # cache key for this dashboard & insight filter combination
    filters_hash: models.CharField = models.CharField(max_length=400, null=True, blank=True)

    def save(self, *args, **kwargs) -> None:
        has_no_filters_hash = self.filters_hash is None
        if has_no_filters_hash:
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


def update_filters_hashes(tile_update_candidates):
    tiles_to_update = []

    for tile in tile_update_candidates:
        if tile.insight.filters and tile.insight.filters != {}:
            candidate_filters_hash = generate_insight_cache_key(tile.insight, tile.dashboard)
            if tile.filters_hash != candidate_filters_hash:
                tile.filters_hash = candidate_filters_hash
                tiles_to_update.append(tile)

    if len(tiles_to_update):
        DashboardTile.objects.bulk_update(tiles_to_update, ["filters_hash"])
