"""Usage signals aggregation for Salesforce enrichment."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from django.db.models import Count, Max

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import tags_context
from posthog.models import Dashboard, Insight, OrganizationMembership, Team

logger = structlog.get_logger(__name__)

CH_BILLING_SETTINGS = {"max_execution_time": 5 * 60}

# Mapping of product attribute names to their output names
PRODUCT_FLAGS = {
    "has_feature_flags": "feature_flags",
    "has_surveys": "surveys",
    "has_error_tracking": "error_tracking",
    "has_ai": "ai",
}


@dataclass
class TeamUsageSignals:
    """Usage signals for a single team from ClickHouse."""

    team_id: int
    active_persons: int = 0
    active_distinct_ids: int = 0
    session_count: int = 0
    total_events: int = 0
    has_feature_flags: bool = False
    has_surveys: bool = False
    has_error_tracking: bool = False
    has_ai: bool = False


@dataclass
class OrgAggregatedSignals:
    """Aggregated signals at organization level (from multiple teams)."""

    active_users: int = 0
    sessions: int = 0
    total_events: int = 0
    events_per_session: float | None = None
    products_activated: list[str] = field(default_factory=list)


@dataclass
class UsageSignals:
    """Complete usage signals for an organization across 7-day and 30-day periods."""

    # 7-day metrics (current period)
    active_users_7d: int = 0
    sessions_7d: int = 0
    events_per_session_7d: float | None = None
    insights_per_user_7d: float | None = None
    dashboards_per_user_7d: float | None = None
    products_activated_7d: list[str] = field(default_factory=list)

    # 30-day metrics (current period)
    active_users_30d: int = 0
    sessions_30d: int = 0
    events_per_session_30d: float | None = None
    insights_per_user_30d: float | None = None
    dashboards_per_user_30d: float | None = None
    products_activated_30d: list[str] = field(default_factory=list)

    # 7-day momentum (percentage change vs previous 7 days)
    active_users_7d_momentum: float | None = None
    sessions_7d_momentum: float | None = None
    events_per_session_7d_momentum: float | None = None

    # 30-day momentum (percentage change vs previous 30 days)
    active_users_30d_momentum: float | None = None
    sessions_30d_momentum: float | None = None
    events_per_session_30d_momentum: float | None = None

    # Current (not period-based)
    days_since_last_login: int | None = None


def calc_momentum(current: float, previous: float) -> float | None:
    """Calculate momentum as percentage change (None if previous is zero)."""
    if previous == 0:
        return None
    return ((current - previous) / previous) * 100


def aggregate_teams_to_org(team_signals: list[TeamUsageSignals]) -> OrgAggregatedSignals:
    """Aggregate team-level signals to organization level (sums metrics, ORs product flags)."""
    if not team_signals:
        return OrgAggregatedSignals()

    total_active_users = sum(t.active_persons for t in team_signals)
    total_sessions = sum(t.session_count for t in team_signals)
    total_events = sum(t.total_events for t in team_signals)

    events_per_session = total_events / total_sessions if total_sessions > 0 else None

    # OR product activation across teams using the PRODUCT_FLAGS mapping
    products = [
        product_name for attr, product_name in PRODUCT_FLAGS.items() if any(getattr(t, attr) for t in team_signals)
    ]

    return OrgAggregatedSignals(
        active_users=total_active_users,
        sessions=total_sessions,
        total_events=total_events,
        events_per_session=events_per_session,
        products_activated=products,
    )


def get_org_login_recency(org_ids: list[str]) -> dict[str, int | None]:
    """Get days since last login for each organization (most recent user login)."""
    if not org_ids:
        return {}

    now = datetime.now(tz=UTC)

    org_logins = (
        OrganizationMembership.objects.filter(organization_id__in=org_ids)
        .values("organization_id")
        .annotate(most_recent_login=Max("user__last_login"))
    )

    return {
        str(entry["organization_id"]): (now - entry["most_recent_login"]).days if entry["most_recent_login"] else None
        for entry in org_logins
    }


def _get_org_model_count(
    model: type[Dashboard] | type[Insight], org_ids: list[str], period_start: datetime, period_end: datetime
) -> dict[str, int]:
    """Get count of model instances created per organization in the given period."""
    if not org_ids:
        return {}

    counts = (
        model.objects.filter(
            team__organization_id__in=org_ids,
            created_at__gte=period_start,
            created_at__lt=period_end,
            deleted=False,
        )
        .values("team__organization_id")
        .annotate(count=Count("id"))
    )

    return {str(entry["team__organization_id"]): entry["count"] for entry in counts}


def get_org_dashboards_count(org_ids: list[str], period_start: datetime, period_end: datetime) -> dict[str, int]:
    """Get count of dashboards created per organization in the given period."""
    return _get_org_model_count(Dashboard, org_ids, period_start, period_end)


def get_org_insights_count(org_ids: list[str], period_start: datetime, period_end: datetime) -> dict[str, int]:
    """Get count of insights created per organization in the given period."""
    return _get_org_model_count(Insight, org_ids, period_start, period_end)


def get_team_ids_for_orgs(org_ids: list[str]) -> dict[str, list[int]]:
    """Get mapping of organization IDs to their team IDs."""
    if not org_ids:
        return {}

    teams = Team.objects.filter(organization_id__in=org_ids).values("id", "organization_id")

    result: dict[str, list[int]] = {org_id: [] for org_id in org_ids}
    for team in teams:
        org_id = str(team["organization_id"])
        if org_id in result:
            result[org_id].append(team["id"])

    return result


def get_teams_with_usage_signals_in_period(
    begin: datetime, end: datetime, team_ids: list[int]
) -> list[TeamUsageSignals]:
    """Get comprehensive usage signals per team for a period from ClickHouse."""
    if not team_ids:
        return []

    query = """
        SELECT
            team_id,
            count(distinct person_id) as active_persons,
            count(distinct distinct_id) as active_distinct_ids,
            count(distinct `$session_id`) as session_count,
            count() as total_events,
            countIf(event = 'decide usage') > 0
                OR countIf(event = 'local evaluation usage') > 0 as has_feature_flags,
            countIf(event = 'survey sent') > 0 as has_surveys,
            countIf(event = '$exception') > 0 as has_error_tracking,
            countIf(event IN ('$ai_generation', '$ai_trace')) > 0 as has_ai
        FROM events
        WHERE team_id IN %(team_ids)s
          AND timestamp >= %(begin)s AND timestamp < %(end)s
        GROUP BY team_id
    """

    with tags_context(usage_report="salesforce_usage_signals"):
        results = sync_execute(
            query,
            {"team_ids": team_ids, "begin": begin, "end": end},
            workload=Workload.OFFLINE,
            settings=CH_BILLING_SETTINGS,
        )

    return [
        TeamUsageSignals(
            team_id=row[0],
            active_persons=row[1],
            active_distinct_ids=row[2],
            session_count=row[3],
            total_events=row[4],
            has_feature_flags=bool(row[5]),
            has_surveys=bool(row[6]),
            has_error_tracking=bool(row[7]),
            has_ai=bool(row[8]),
        )
        for row in results
    ]


def get_teams_with_recordings_in_period(begin: datetime, end: datetime, team_ids: list[int]) -> dict[int, int]:
    """Get session recording counts per team for sessions that started within the period."""
    if not team_ids:
        return {}
    if begin >= end:
        return {}

    previous_begin = begin - (end - begin)

    # Aggregate all sessions from previous_begin to end, then filter to those
    # whose first timestamp is within the target period. This avoids NOT IN subquery.
    query = """
        SELECT team_id, countIf(first_ts >= %(begin)s AND first_ts < %(end)s) as count
        FROM (
            SELECT team_id, session_id, min(min_first_timestamp) as first_ts
            FROM session_replay_events
            WHERE team_id IN %(team_ids)s
              AND min_first_timestamp >= %(previous_begin)s AND min_first_timestamp < %(end)s
            GROUP BY team_id, session_id
        )
        GROUP BY team_id
        HAVING count > 0
    """

    with tags_context(usage_report="salesforce_recordings_signals"):
        results = sync_execute(
            query,
            {"team_ids": team_ids, "previous_begin": previous_begin, "begin": begin, "end": end},
            workload=Workload.OFFLINE,
            settings=CH_BILLING_SETTINGS,
        )

    return {row[0]: row[1] for row in results}


@dataclass
class _PeriodData:
    """Internal data structure for a single time period's metrics."""

    signals_by_team: dict[int, TeamUsageSignals]
    prev_signals_by_team: dict[int, TeamUsageSignals]
    recordings: dict[int, int]
    dashboards: dict[str, int]
    insights: dict[str, int]


def _calc_eps_momentum(current: OrgAggregatedSignals, previous: OrgAggregatedSignals) -> float | None:
    """Calculate events-per-session momentum if both values are present."""
    if current.events_per_session is None or previous.events_per_session is None:
        return None
    return calc_momentum(current.events_per_session, previous.events_per_session)


def _get_products_with_recordings(products: list[str], team_ids: list[int], recordings: dict[int, int]) -> list[str]:
    """Add recordings to products list if any team has recordings."""
    has_recordings = any(recordings.get(tid, 0) > 0 for tid in team_ids)
    if has_recordings and "recordings" not in products:
        return [*products, "recordings"]
    return products


def _per_user_metric(count: int, active_users: int) -> float | None:
    """Calculate per-user metric, returning None if no active users."""
    return count / active_users if active_users > 0 else None


def aggregate_usage_signals_for_orgs(org_ids: list[str]) -> dict[str, UsageSignals]:
    """Aggregate complete usage signals for a list of organizations."""
    if not org_ids:
        return {}

    logger.info("aggregating_usage_signals", org_count=len(org_ids))
    now = datetime.now(tz=UTC)

    # Define time periods
    p7_start, p7_end = now - timedelta(days=7), now
    p7_prev_start = p7_start - timedelta(days=7)
    p30_start, p30_end = now - timedelta(days=30), now
    p30_prev_start = p30_start - timedelta(days=30)

    org_to_teams = get_team_ids_for_orgs(org_ids)
    all_team_ids = [tid for teams in org_to_teams.values() for tid in teams]

    if not all_team_ids:
        return {org_id: UsageSignals() for org_id in org_ids}

    # Fetch all period data
    def fetch_period_data(start: datetime, end: datetime, prev_start: datetime) -> _PeriodData:
        signals = get_teams_with_usage_signals_in_period(start, end, all_team_ids)
        prev_signals = get_teams_with_usage_signals_in_period(prev_start, start, all_team_ids)
        return _PeriodData(
            signals_by_team={s.team_id: s for s in signals},
            prev_signals_by_team={s.team_id: s for s in prev_signals},
            recordings=get_teams_with_recordings_in_period(start, end, all_team_ids),
            dashboards=get_org_dashboards_count(org_ids, start, end),
            insights=get_org_insights_count(org_ids, start, end),
        )

    p7 = fetch_period_data(p7_start, p7_end, p7_prev_start)
    p30 = fetch_period_data(p30_start, p30_end, p30_prev_start)
    login_recency = get_org_login_recency(org_ids)

    result: dict[str, UsageSignals] = {}
    for org_id in org_ids:
        team_ids = org_to_teams.get(org_id, [])

        # Aggregate current and previous periods for 7d and 30d
        agg_7d = aggregate_teams_to_org([p7.signals_by_team[tid] for tid in team_ids if tid in p7.signals_by_team])
        agg_7d_prev = aggregate_teams_to_org(
            [p7.prev_signals_by_team[tid] for tid in team_ids if tid in p7.prev_signals_by_team]
        )
        agg_30d = aggregate_teams_to_org([p30.signals_by_team[tid] for tid in team_ids if tid in p30.signals_by_team])
        agg_30d_prev = aggregate_teams_to_org(
            [p30.prev_signals_by_team[tid] for tid in team_ids if tid in p30.prev_signals_by_team]
        )

        result[org_id] = UsageSignals(
            # 7-day metrics
            active_users_7d=agg_7d.active_users,
            sessions_7d=agg_7d.sessions,
            events_per_session_7d=agg_7d.events_per_session,
            insights_per_user_7d=_per_user_metric(p7.insights.get(org_id, 0), agg_7d.active_users),
            dashboards_per_user_7d=_per_user_metric(p7.dashboards.get(org_id, 0), agg_7d.active_users),
            products_activated_7d=_get_products_with_recordings(agg_7d.products_activated, team_ids, p7.recordings),
            # 30-day metrics
            active_users_30d=agg_30d.active_users,
            sessions_30d=agg_30d.sessions,
            events_per_session_30d=agg_30d.events_per_session,
            insights_per_user_30d=_per_user_metric(p30.insights.get(org_id, 0), agg_30d.active_users),
            dashboards_per_user_30d=_per_user_metric(p30.dashboards.get(org_id, 0), agg_30d.active_users),
            products_activated_30d=_get_products_with_recordings(agg_30d.products_activated, team_ids, p30.recordings),
            # 7-day momentum
            active_users_7d_momentum=calc_momentum(agg_7d.active_users, agg_7d_prev.active_users),
            sessions_7d_momentum=calc_momentum(agg_7d.sessions, agg_7d_prev.sessions),
            events_per_session_7d_momentum=_calc_eps_momentum(agg_7d, agg_7d_prev),
            # 30-day momentum
            active_users_30d_momentum=calc_momentum(agg_30d.active_users, agg_30d_prev.active_users),
            sessions_30d_momentum=calc_momentum(agg_30d.sessions, agg_30d_prev.sessions),
            events_per_session_30d_momentum=_calc_eps_momentum(agg_30d, agg_30d_prev),
            # Current
            days_since_last_login=login_recency.get(org_id),
        )

    logger.info("aggregated_usage_signals", org_count=len(org_ids), results_count=len(result))
    return result
