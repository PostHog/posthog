from datetime import timedelta
from enum import Enum
from functools import cached_property
from typing import List, Optional, Union

import structlog
from django.core.paginator import Paginator
from django.utils.timezone import now

from posthog.caching.calculate_results import calculate_cache_key
from posthog.caching.utils import active_teams
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.insight import Insight, InsightViewed
from posthog.models.insight_caching_state import InsightCachingState
from posthog.models.team import Team
from posthog.models.utils import UUIDT

VERY_RECENTLY_VIEWED_THRESHOLD = timedelta(hours=48)
GENERALLY_VIEWED_THRESHOLD = timedelta(weeks=2)

logger = structlog.get_logger(__name__)


# :TODO: Make these configurable
class TargetCacheAge(Enum):
    NO_CACHING = None
    LOW_PRIORITY = timedelta(days=7)
    MID_PRIORITY = timedelta(hours=24)
    HIGH_PRIORITY = timedelta(hours=12)


INSERT_INSIGHT_CACHING_STATES_QUERY = """
INSERT INTO posthog_insightcachingstate AS state (
    id,
    team_id,
    insight_id,
    dashboard_tile_id,
    cache_key,
    target_cache_age_seconds,
    created_at,
    updated_at,
    refresh_attempt
)
VALUES {values}
ON CONFLICT (insight_id, coalesce(dashboard_tile_id, -1)) DO UPDATE SET
    last_refresh = (SELECT CASE WHEN state.cache_key != EXCLUDED.cache_key THEN NULL ELSE state.last_refresh END AS new_last_refresh),
    last_refresh_queued_at = (SELECT CASE WHEN state.cache_key != EXCLUDED.cache_key THEN NULL ELSE state.last_refresh_queued_at END AS new_last_refresh_queued_at),
    refresh_attempt = (SELECT CASE WHEN state.cache_key != EXCLUDED.cache_key THEN 0 ELSE state.refresh_attempt END AS new_refresh_attempt),
    cache_key = EXCLUDED.cache_key,
    target_cache_age_seconds = EXCLUDED.target_cache_age_seconds,
    updated_at = EXCLUDED.updated_at
"""


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


cacheable_query_kinds = [
    "EventsQuery",
    "HogQLQuery",
    "TimeToSeeDataSessionsQuery",
    "TimeToSeeDataQuery",
]


def insight_can_be_cached(insight: Optional[Insight]) -> bool:
    if insight is None:
        return False

    cacheable_filter_based_insight = len(insight.filters) > 0
    cacheable_query_based_insight = insight.query is not None and (
        insight.query.get("kind", None) in cacheable_query_kinds
        or insight.query.get("source", {}).get("kind") in cacheable_query_kinds
    )
    return cacheable_filter_based_insight or cacheable_query_based_insight


def sync_insight_cache_states():
    lazy_loader = LazyLoader()
    insights = Insight.objects.all().prefetch_related("team", "sharingconfiguration_set").order_by("pk")
    for page_of_insights in _iterate_large_queryset(insights, 1000):
        batch = [upsert(insight.team, insight, lazy_loader, execute=False) for insight in page_of_insights]
        _execute_insert(batch)

    tiles = (
        DashboardTile.objects.all()
        .filter(insight__isnull=False)
        .prefetch_related(
            "dashboard",
            "dashboard__sharingconfiguration_set",
            "insight",
            "insight__team",
        )
        .order_by("pk")
    )

    for page_of_tiles in _iterate_large_queryset(tiles, 1000):
        batch = [upsert(tile.insight.team, tile, lazy_loader, execute=False) for tile in page_of_tiles]
        _execute_insert(batch)


def upsert(
    team: Team,
    target: Union[DashboardTile, Insight],
    lazy_loader: Optional[LazyLoader] = None,
    execute=True,
) -> Optional[InsightCachingState]:
    lazy_loader = lazy_loader or LazyLoader()
    cache_key = calculate_cache_key(target)
    if cache_key is None:  # Non-cachable model
        return None

    target_age = calculate_target_age(team, target, lazy_loader)
    target_cache_age_seconds = target_age.value.total_seconds() if target_age.value is not None else None

    model = InsightCachingState(
        team_id=team.pk,
        insight=target if isinstance(target, Insight) else target.insight,
        dashboard_tile=target if isinstance(target, DashboardTile) else None,
        cache_key=cache_key,
        target_cache_age_seconds=target_cache_age_seconds,
    )
    if execute:
        _execute_insert([model])
        return None
    else:
        return model


def sync_insight_caching_state(
    team_id: int,
    insight_id: Optional[int] = None,
    dashboard_tile_id: Optional[int] = None,
):
    try:
        team = Team.objects.get(pk=team_id)
        item: Optional[DashboardTile | Insight] = None
        if dashboard_tile_id is not None:
            item = DashboardTile.objects_including_soft_deleted.get(pk=dashboard_tile_id)
        elif insight_id is not None:
            item = Insight.objects_including_soft_deleted.get(pk=insight_id)
        if not item:
            raise ValueError("Either insight_id or dashboard_tile_id must be provided")
        if not item.deleted:
            upsert(team, item)
    except Exception as err:
        # This is a best-effort kind synchronization, safe to ignore errors
        logger.warn(
            "Failed to sync InsightCachingState, ignoring",
            exception=err,
            team_id=team_id,
            insight_id=insight_id,
            dashboard_tile_id=dashboard_tile_id,
        )


def calculate_target_age(team: Team, target: Union[DashboardTile, Insight], lazy_loader: LazyLoader) -> TargetCacheAge:
    if isinstance(target, Insight):
        return calculate_target_age_insight(team, target, lazy_loader)
    else:
        return calculate_target_age_dashboard_tile(team, target, lazy_loader)


def calculate_target_age_insight(team: Team, insight: Insight, lazy_loader: LazyLoader) -> TargetCacheAge:
    if team.pk not in lazy_loader.active_teams:
        return TargetCacheAge.NO_CACHING

    if insight.deleted or not insight_can_be_cached(insight):
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

    if (
        not dashboard_tile.insight
        or dashboard_tile.insight.deleted
        or not insight_can_be_cached(dashboard_tile.insight)
    ):
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

        yield page.object_list


def _execute_insert(states: List[Optional[InsightCachingState]]):
    from django.db import connection

    models: List[InsightCachingState] = list(filter(None, states))
    if len(models) == 0:
        return

    timestamp = now()
    values = []
    params = []
    for state in models:
        values.append("(%s, %s, %s, %s, %s, %s, %s, %s, 0)")
        params.extend(
            [
                UUIDT(),
                state.team_id,
                state.insight_id,
                state.dashboard_tile_id,
                state.cache_key,
                state.target_cache_age_seconds,
                timestamp,
                timestamp,
            ]
        )

    with connection.cursor() as cursor:
        query = INSERT_INSIGHT_CACHING_STATES_QUERY.format(values=", ".join(values))
        cursor.execute(query, params=params)
