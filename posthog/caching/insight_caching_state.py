from calendar import timegm
from datetime import timedelta
from enum import Enum
from functools import cached_property
from typing import Optional, Union

from django.db.models.query import F, Q, QuerySet
from django.utils.timezone import now

from posthog.caching.utils import active_teams
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.insight import Insight, InsightViewed, generate_insight_cache_key
from posthog.models.insight_caching_state import InsightCachingState
from posthog.models.team import Team

VERY_RECENTLY_VIEWED_THRESHOLD = timedelta(hours=48)
GENERALLY_VIEWED_THRESHOLD = timedelta(weeks=2)
MAX_ATTEMPTS = 3


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
        recently_viewed_insights = (
            InsightViewed.objects.filter(last_viewed_at__gte=now() - VERY_RECENTLY_VIEWED_THRESHOLD)
            .distinct("insight_id")
        )
        return set(recently_viewed_insights.values_list("insight_id", flat=True))


def upsert(team: Team, target: Union[DashboardTile, Insight], lazy_loader: Optional[LazyLoader] = None):
    lazy_loader = lazy_loader or LazyLoader()
    cache_key = calculate_cache_key(team, target)
    if cache_key is None:  # Non-cachable model
        return

    target_age = calculate_target_age(team, target, lazy_loader)
    InsightCachingState.objects.update_or_create(
        team_id=team.pk,
        insight=target if isinstance(target, Insight) else None,
        dashboard_tile=target if isinstance(target, DashboardTile) else None,
        defaults={
            "cache_key": cache_key,
            "target_cache_age_seconds": target_age,
        },
    )


def fetch_states_in_need_of_updating(timestamp=None) -> QuerySet[InsightCachingState]:
    if timestamp is None:
        timestamp = now()

    unix_timestamp = timegm(now().utctimetuple())
    return InsightCachingState.objects.filter(
        Q(last_refresh__isnull=True) | Q(last_refresh__lte=unix_timestamp - F("target_cache_age_seconds"))
    ).filter(refresh_attempt__lte=MAX_ATTEMPTS)


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

    # :TODO: Only cache insights that are shared

    if insight.pk not in lazy_loader.recently_viewed_insights:
        return TargetCacheAge.NO_CACHING

    return TargetCacheAge.MID_PRIORITY


def calculate_target_age_dashboard_tile(
    team: Team, dashboard_tile: DashboardTile, lazy_loader: LazyLoader
) -> TargetCacheAge:
    if team.pk not in lazy_loader.active_teams:
        return TargetCacheAge.NO_CACHING

    if dashboard_tile.dashboard.deleted:
        return TargetCacheAge.NO_CACHING

    if not dashboard_tile.insight or dashboard_tile.insight.deleted or len(dashboard_tile.insight.filters) == 0:
        return TargetCacheAge.NO_CACHING

    if dashboard_tile.dashboard_id == team.primary_dashboard_id:
        return TargetCacheAge.HIGH_PRIORITY

    # :TODO: If shared, MID_PRIORITY

    since_last_viewed = now() - dashboard_tile.dashboard.last_accessed_at
    if since_last_viewed < VERY_RECENTLY_VIEWED_THRESHOLD:
        return TargetCacheAge.HIGH_PRIORITY

    if since_last_viewed < GENERALLY_VIEWED_THRESHOLD:
        return TargetCacheAge.MID_PRIORITY

    return TargetCacheAge.LOW_PRIORITY
