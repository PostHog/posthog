"""Pure-SQL candidate metric selection for Pulse.

v1 strategy: top-N popular insights and high-volume events. No LLM.
"""

from datetime import UTC, datetime, timedelta

from django.db.models import Count, Q

from posthog.models import Dashboard, DashboardTile, Insight, InsightViewed, Team
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.pulse.types import CandidateMetric, MetricDescriptor

RECENT_DAYS = 30
MIN_VIEWERS_FOR_RECENT_INSIGHT = 3
TOP_DASHBOARD_LIMIT = 5
TOP_EVENT_LIMIT = 10


def _trends_query_from_insight(insight: Insight) -> dict | None:
    """Extract a re-executable TrendsQuery from a saved Insight, or None if unsupported."""
    query = insight.query
    if not query:
        return None
    while isinstance(query, dict) and query.get("source"):
        query = query["source"]
    if not isinstance(query, dict) or query.get("kind") != "TrendsQuery":
        return None
    return query


def _build_event_volume_query(event_name: str) -> dict:
    return {
        "kind": "TrendsQuery",
        "series": [
            {"kind": "EventsNode", "event": event_name, "name": event_name, "math": "total"}
        ],
        "dateRange": {"date_from": "-30d", "date_to": None},
        "interval": "day",
    }


def _insight_to_candidate(insight: Insight, source: str) -> CandidateMetric | None:
    query = _trends_query_from_insight(insight)
    if not query:
        return None
    return CandidateMetric(
        descriptor=MetricDescriptor(
            source=source,
            source_id=insight.id,
            label=insight.name or insight.derived_name or f"Insight {insight.short_id}",
            query=query,
        )
    )


def _select_dashboard_tile_candidates(team: Team, limit: int) -> list[CandidateMetric]:
    """Pick Trends insights on the team's most-pinned/visible dashboards."""
    dashboards = (
        Dashboard.objects.filter(team=team, deleted=False)
        .filter(Q(pinned=True) | Q(last_accessed_at__gte=datetime.now(UTC) - timedelta(days=RECENT_DAYS)))
        .order_by("-pinned", "-last_accessed_at")[:limit]
    )
    tiles = (
        DashboardTile.objects.filter(dashboard__in=dashboards, deleted=False, insight__isnull=False)
        .select_related("insight")
        .order_by("dashboard_id", "id")
    )
    candidates: list[CandidateMetric] = []
    seen_insight_ids: set[int] = set()
    for tile in tiles:
        insight = tile.insight
        if insight is None or insight.id in seen_insight_ids:
            continue
        seen_insight_ids.add(insight.id)
        candidate = _insight_to_candidate(insight, source="dashboard_tile")
        if candidate:
            candidates.append(candidate)
    return candidates


def _select_recent_viewed_insight_candidates(
    team: Team, limit: int, existing_ids: set[int]
) -> list[CandidateMetric]:
    """Pick Trends insights recently viewed by multiple team members."""
    since = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
    viewed = (
        InsightViewed.objects.filter(team=team, last_viewed_at__gte=since)
        .values("insight_id")
        .annotate(viewer_count=Count("user_id", distinct=True))
        .filter(viewer_count__gte=MIN_VIEWERS_FOR_RECENT_INSIGHT)
        .order_by("-viewer_count")
    )
    insight_ids = [v["insight_id"] for v in viewed if v["insight_id"] not in existing_ids]
    insights = Insight.objects.filter(id__in=insight_ids, deleted=False)

    candidates: list[CandidateMetric] = []
    for insight in insights:
        candidate = _insight_to_candidate(insight, source="recent_insight")
        if candidate:
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
    return candidates


def _select_top_event_candidates(team: Team, limit: int) -> list[CandidateMetric]:
    """Pick the team's highest-volume events as candidate metrics."""
    from posthog.models import EventDefinition

    base_qs = EventDefinition.objects.filter(team=team).exclude(name__startswith="$")
    # Prefer events with computed 30-day usage stats.
    events = list(
        base_qs.exclude(query_usage_30_day__isnull=True).order_by("-query_usage_30_day")[:limit]
    )
    if len(events) < limit:
        seen = {e.id for e in events}
        backfill = base_qs.exclude(id__in=seen).order_by("-last_seen_at")[: limit - len(events)]
        events.extend(backfill)

    return [
        CandidateMetric(
            descriptor=MetricDescriptor(
                source="top_event",
                source_id=event.id,
                label=event.name,
                query=_build_event_volume_query(event.name),
            )
        )
        for event in events
    ]


@database_sync_to_async
def _select_sync(team_id: int, max_candidates: int) -> list[CandidateMetric]:
    team = Team.objects.get(id=team_id)
    candidates = _select_dashboard_tile_candidates(team, TOP_DASHBOARD_LIMIT)
    seen_ids = {c.descriptor.source_id for c in candidates if isinstance(c.descriptor.source_id, int)}
    candidates.extend(_select_recent_viewed_insight_candidates(team, max_candidates // 2, seen_ids))
    candidates.extend(_select_top_event_candidates(team, TOP_EVENT_LIMIT))
    return candidates[:max_candidates]


async def select_candidates(team_id: int, max_candidates: int) -> list[CandidateMetric]:
    return await _select_sync(team_id, max_candidates)
