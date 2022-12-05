from datetime import timedelta
from enum import Enum
from functools import cached_property
from typing import Optional, Union

import structlog
from django.core.paginator import Paginator
from django.utils.timezone import now

from posthog.caching.utils import active_teams
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.insight import Insight, InsightViewed, generate_insight_cache_key
from posthog.models.insight_caching_state import InsightCachingState
from posthog.models.team import Team

VERY_RECENTLY_VIEWED_THRESHOLD = timedelta(hours=48)
GENERALLY_VIEWED_THRESHOLD = timedelta(weeks=2)

logger = structlog.get_logger(__name__)

# :TODO: Make these configurable
class TargetCacheAge(Enum):
    NO_CACHING = None
    LOW_PRIORITY = timedelta(days=7)
    MID_PRIORITY = timedelta(hours=24)
    HIGH_PRIORITY = timedelta(hours=12)


# Helps do large-scale re-calculations efficiently by loading some data only once
class LazyLoader:
    @cached_property
    def active_teams(self):
        return active_teams()

    @cached_property
    def recently_viewed_insights(self):
        recently_viewed_insights = InsightViewed.objects.filter(
            last_viewed_at__gte=now() - VERY_RECENTLY_VIEWED_THRESHOLD
        ).distinct("insight_id")
        return set(recently_viewed_insights.values_list("insight_id", flat=True))


def sync_insight_cache_states():
    lazy_loader = LazyLoader()

    insights = Insight.objects.all().prefetch_related("team", "sharingconfiguration_set").order_by("pk")
    for insight in _iterate_large_queryset(insights, 1000):
        upsert(insight.team, insight, lazy_loader)

    tiles = (
        DashboardTile.objects.all()
        .prefetch_related("dashboard", "dashboard__team", "dashboard__sharingconfiguration_set", "insight")
        .order_by("pk")
    )
    for tile in _iterate_large_queryset(tiles, 1000):
        upsert(tile.dashboard.team, tile, lazy_loader)


def upsert(
    team: Team, target: Union[DashboardTile, Insight], lazy_loader: Optional[LazyLoader] = None
) -> Optional[InsightCachingState]:
    lazy_loader = lazy_loader or LazyLoader()
    cache_key = calculate_cache_key(team, target)
    if cache_key is None:  # Non-cachable model
        return None

    target_age = calculate_target_age(team, target, lazy_loader)
    target_age_seconds = target_age.value.total_seconds() if target_age.value is not None else None
    caching_state, _ = InsightCachingState.objects.update_or_create(
        team_id=team.pk,
        insight=target if isinstance(target, Insight) else target.insight,
        dashboard_tile=target if isinstance(target, DashboardTile) else None,
        defaults={
            "cache_key": cache_key,
            "target_cache_age_seconds": target_age_seconds,
        },
    )
    return caching_state


def sync_insight_caching_state(team_id: int, insight_id: Optional[int] = None, dashboard_tile_id: Optional[int] = None):
    try:
        team = Team.objects.get(pk=team_id)
        if dashboard_tile_id is not None:
            upsert(team, DashboardTile.objects.get(pk=dashboard_tile_id))
        elif insight_id is not None:
            upsert(team, Insight.objects.get(pk=insight_id))
    except Exception as err:
        # This is a best-effort kind synchronization, safe to ignore errors
        logger.warn("Failed to sync InsightCachingState, ignoring", exception=err)


def calculate_cache_key(team: Team, target: Union[DashboardTile, Insight]) -> Optional[str]:
    insight = target if isinstance(target, Insight) else target.insight
    if insight is None:
        return None

    return generate_insight_cache_key(insight, insight.dashboard)


def calculate_target_age(team: Team, target: Union[DashboardTile, Insight], lazy_loader: LazyLoader) -> TargetCacheAge:
    if isinstance(target, Insight):
        return calculate_target_age_insight(team, target, lazy_loader)
    else:
        return calculate_target_age_dashboard_tile(team, target, lazy_loader)


def calculate_target_age_insight(team: Team, insight: Insight, lazy_loader: LazyLoader) -> TargetCacheAge:
    if team.pk not in lazy_loader.active_teams:
        return TargetCacheAge.NO_CACHING

    if insight.deleted or len(insight.filters) == 0:
        return TargetCacheAge.NO_CACHING

    if insight.pk not in lazy_loader.recently_viewed_insights:
        return TargetCacheAge.NO_CACHING

    if insight.is_sharing_enabled:
        return TargetCacheAge.MID_PRIORITY

    return TargetCacheAge.NO_CACHING


def calculate_target_age_dashboard_tile(
    team: Team, dashboard_tile: DashboardTile, lazy_loader: LazyLoader
) -> TargetCacheAge:
    if team.pk not in lazy_loader.active_teams:
        return TargetCacheAge.NO_CACHING

    if dashboard_tile.deleted or dashboard_tile.dashboard.deleted:
        return TargetCacheAge.NO_CACHING

    if not dashboard_tile.insight or dashboard_tile.insight.deleted or len(dashboard_tile.insight.filters) == 0:
        return TargetCacheAge.NO_CACHING

    if dashboard_tile.dashboard_id == team.primary_dashboard_id:
        return TargetCacheAge.HIGH_PRIORITY

    since_last_viewed = (
        now() - dashboard_tile.dashboard.last_accessed_at
        if dashboard_tile.dashboard.last_accessed_at
        else timedelta(days=9999)
    )
    if since_last_viewed < VERY_RECENTLY_VIEWED_THRESHOLD:
        return TargetCacheAge.HIGH_PRIORITY

    if since_last_viewed < GENERALLY_VIEWED_THRESHOLD:
        return TargetCacheAge.MID_PRIORITY

    if dashboard_tile.dashboard.is_sharing_enabled:
        return TargetCacheAge.LOW_PRIORITY

    return TargetCacheAge.NO_CACHING


def _iterate_large_queryset(queryset, page_size):
    paginator = Paginator(queryset, page_size)
    for page_number in paginator.page_range:
        page = paginator.page(page_number)

        for item in page.object_list:
            yield item
