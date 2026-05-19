from datetime import datetime
from typing import TYPE_CHECKING, Optional

import structlog

from posthog.schema import EventPropertyFilter, PropertyOperator

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.instance_setting import get_instance_setting

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
)

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner

logger = structlog.get_logger(__name__)

# Bucketing the precompute hourly keeps reads correct for any whole-hour-offset
# timezone — boundaries line up exactly when the team-local window is converted
# to UTC before filtering on `time_window_start`.
LAZY_TTL_SECONDS: dict[str, int] = {
    "0d": 15 * 60,
    "1d": 60 * 60,
    "7d": 24 * 60 * 60,
    "default": 7 * 24 * 60 * 60,
}

# Today the gate accepts: empty user filters, or a single EventPropertyFilter
# on `$host` with operator `exact`. Test-account filters are always allowed
# (their content is hashed into the cache key).
SUPPORTED_USER_FILTER_KEYS: set[str] = {"$host"}


def can_use_lazy_precompute(runner: "WebOverviewQueryRunner") -> bool:
    query = runner.query

    # Gate rollout per-team via instance setting (defaults to empty list = disabled).
    enabled_team_ids = get_instance_setting("WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS") or []
    if runner.team.pk not in enabled_team_ids:
        return False

    if query.conversionGoal is not None:
        return False

    if query.sampling is not None and getattr(query.sampling, "enabled", False):
        return False

    for prop in query.properties or []:
        if not isinstance(prop, EventPropertyFilter):
            return False
        if prop.key not in SUPPORTED_USER_FILTER_KEYS:
            return False
        if prop.operator != PropertyOperator.EXACT:
            return False

    date_to = runner.query_date_range.date_to()
    if date_to is None:
        return False

    return True


def _user_filter_expr(runner: "WebOverviewQueryRunner") -> ast.Expr:
    """Build the AST expression that gets substituted into the INSERT's WHERE clause.

    The substituted AST is what `ensure_precomputed` hashes into the cache key —
    different filter values therefore become different precomputed jobs.
    """
    if not runner.query.properties:
        return ast.Constant(value=True)

    # Gate already enforces single EventPropertyFilter with $host exact.
    host_filter = runner.query.properties[0]
    assert isinstance(host_filter, EventPropertyFilter)
    return ast.Call(
        name="equals",
        args=[
            ast.Field(chain=["events", "properties", host_filter.key]),
            ast.Constant(value=host_filter.value),
        ],
    )


def _test_account_filter_expr(runner: "WebOverviewQueryRunner") -> ast.Expr:
    """Test-account filters land in the placeholder set, so they also shape the cache key.

    `_test_account_filters` may be an empty list when filterTestAccounts is False
    or the project has none configured.
    """
    from posthog.hogql.property import property_to_expr

    if not runner._test_account_filters:
        return ast.Constant(value=True)
    return property_to_expr(runner._test_account_filters, team=runner.team)


def _events_session_id_expr(runner: "WebOverviewQueryRunner") -> ast.Expr:
    return runner.events_session_property


# HogQL template for the precompute INSERT. The lazy_computation framework
# substitutes the listed placeholders (including `time_window_min`/`time_window_max`),
# parses the result, and INSERTs into `web_overview_preaggregated`. The framework
# automatically prepends `team_id`, `job_id` and appends `expires_at` to the SELECT.
INSERT_QUERY_TEMPLATE = """
SELECT
    toStartOfHour(start_timestamp) AS time_window_start,
    uniqState(session_person_id) AS uniq_users_state,
    uniqState(session_id) AS uniq_sessions_state,
    sumState(assumeNotNull(toInt(filtered_pageview_count))) AS sum_pageviews_state,
    avgState(assumeNotNull(toFloat(session_duration))) AS avg_duration_state,
    avgState(assumeNotNull(toInt(is_bounce))) AS avg_bounce_state
FROM (
    SELECT
        any(events.person_id) AS session_person_id,
        {events_session_id} AS session_id,
        min(session.$start_timestamp) AS start_timestamp,
        any(session.$session_duration) AS session_duration,
        countIf(or(equals(event, '$pageview'), equals(event, '$screen'))) AS filtered_pageview_count,
        any(session.$is_bounce) AS is_bounce
    FROM events
    WHERE and(
        {events_session_id} IS NOT NULL,
        timestamp >= {time_window_min},
        timestamp < {time_window_max},
        {user_filter},
        {test_account_filter}
    )
    GROUP BY session_id
    HAVING and(
        toStartOfHour(min(session.$start_timestamp)) >= {time_window_min},
        toStartOfHour(min(session.$start_timestamp)) < {time_window_max}
    )
)
GROUP BY time_window_start
"""


def ensure_web_overview_precomputed(
    runner: "WebOverviewQueryRunner",
    time_range_start: datetime,
    time_range_end: datetime,
) -> LazyComputationResult:
    placeholders: dict[str, ast.Expr] = {
        "events_session_id": _events_session_id_expr(runner),
        "user_filter": _user_filter_expr(runner),
        "test_account_filter": _test_account_filter_expr(runner),
    }

    return ensure_precomputed(
        team=runner.team,
        insert_query=INSERT_QUERY_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
        placeholders=placeholders,
    )


def build_read_query(
    job_ids: list[str],
    team_id: int,
    current_start_utc: datetime,
    current_end_utc: datetime,
    previous_start_utc: Optional[datetime],
    previous_end_utc: Optional[datetime],
) -> ast.SelectQuery:
    """Read the precomputed table for current (and optionally previous) period.

    Produces a single row in the shape expected by `WebOverviewQueryRunner._calculate`:
    `[unique_users, prev_unique_users, views, prev_views, sessions, prev_sessions,
      avg_duration, prev_avg_duration, bounce_rate, prev_bounce_rate]`.
    """
    has_compare = previous_start_utc is not None and previous_end_utc is not None

    job_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=str(jid)) for jid in job_ids])

    current_filter = parse_expr(
        "and(time_window_start >= {start}, time_window_start < {end})",
        placeholders={
            "start": ast.Constant(value=current_start_utc),
            "end": ast.Constant(value=current_end_utc),
        },
    )

    if has_compare:
        previous_filter = parse_expr(
            "and(time_window_start >= {start}, time_window_start < {end})",
            placeholders={
                "start": ast.Constant(value=previous_start_utc),
                "end": ast.Constant(value=previous_end_utc),
            },
        )
    else:
        previous_filter = ast.Constant(value=False)

    query = parse_select(
        """
        SELECT
            uniqMergeIf(uniq_users_state, {current}) AS unique_users,
            uniqMergeIf(uniq_users_state, {previous}) AS previous_unique_users,
            sumMergeIf(sum_pageviews_state, {current}) AS views,
            sumMergeIf(sum_pageviews_state, {previous}) AS previous_views,
            uniqMergeIf(uniq_sessions_state, {current}) AS sessions,
            uniqMergeIf(uniq_sessions_state, {previous}) AS previous_sessions,
            avgMergeIf(avg_duration_state, {current}) AS avg_duration,
            avgMergeIf(avg_duration_state, {previous}) AS previous_avg_duration,
            avgMergeIf(avg_bounce_state, {current}) AS bounce_rate,
            avgMergeIf(avg_bounce_state, {previous}) AS previous_bounce_rate
        FROM web_overview_preaggregated
        WHERE and(job_id IN {job_ids}, team_id = {team_id})
        """,
        placeholders={
            "current": current_filter,
            "previous": previous_filter,
            "job_ids": job_ids_tuple,
            "team_id": ast.Constant(value=team_id),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def execute_lazy_precomputed_read(
    runner: "WebOverviewQueryRunner",
) -> Optional[list]:
    """Orchestrate the lazy precompute + read. Returns the response row, or None
    on any failure (caller falls through to the v2/raw path)."""
    try:
        date_from = runner.query_date_range.date_from()
        date_to = runner.query_date_range.date_to()
        assert date_from is not None and date_to is not None

        time_range_start = date_from
        time_range_end = date_to

        if time_range_start >= time_range_end:
            return None

        result = ensure_web_overview_precomputed(
            runner=runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )

        if not result.job_ids:
            return None

        # Convert team-tz date boundaries to UTC for filtering hourly buckets.
        current_start_utc = date_from.astimezone(tz=None).replace(tzinfo=None)
        current_end_utc = date_to.astimezone(tz=None).replace(tzinfo=None)

        previous_start_utc: Optional[datetime] = None
        previous_end_utc: Optional[datetime] = None
        if runner.query_compare_to_date_range is not None:
            prev_from = runner.query_compare_to_date_range.date_from()
            prev_to = runner.query_compare_to_date_range.date_to()
            previous_start_utc = prev_from.astimezone(tz=None).replace(tzinfo=None)
            previous_end_utc = prev_to.astimezone(tz=None).replace(tzinfo=None)

        read_query = build_read_query(
            job_ids=[str(jid) for jid in result.job_ids],
            team_id=runner.team.pk,
            current_start_utc=current_start_utc,
            current_end_utc=current_end_utc,
            previous_start_utc=previous_start_utc,
            previous_end_utc=previous_end_utc,
        )

        response = execute_hogql_query(
            query_type="web_overview_lazy_query",
            query=read_query,
            team=runner.team,
            timings=runner.timings,
            modifiers=runner.modifiers,
            limit_context=runner.limit_context,
        )
        assert response.results
        return response.results[0]
    except Exception:
        logger.exception("web_overview_lazy_precompute_failed", team_id=runner.team.pk)
        return None
