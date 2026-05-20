from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional

import structlog
from prometheus_client import Counter

from posthog.schema import EventPropertyFilter, PropertyOperator

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.web_overview_preaggregated_sql import (
    DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE,
)
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.instance_setting import get_instance_setting

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
    read_precomputed_jobs_if_ready,
)

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner

logger = structlog.get_logger(__name__)

# TTL schedule for precomputed jobs — recent data is refreshed more frequently.
LAZY_TTL_SECONDS: dict[str, int] = {
    "0d": 15 * 60,
    "1d": 60 * 60,
    "7d": 24 * 60 * 60,
    "default": 7 * 24 * 60 * 60,
}

# Gate accepts: no user filters, or a single EventPropertyFilter on `$host` exact+string.
SUPPORTED_USER_FILTER_KEYS: set[str] = {"$host"}

# Upper bound on the precompute span.
MAX_PRECOMPUTE_DAYS = 180

# Width of boundary pad on each side of the per-job event-scan window.
# Sessions starting near midnight can span into the adjacent day; the pad
# ensures trailing events are included. The HAVING clause attributes each
# session to its start hour so no bucket is double-counted.
# See extended rationale in `web_overview_lazy_precompute.py` comments.
SESSION_BOUNDARY_PAD_MINUTES = 24 * 60

WEB_OVERVIEW_LAZY_FAILED = Counter(
    "web_overview_lazy_precompute_failed_total",
    "Lazy precompute path failures, by error class",
    ["error_type"],
)

WEB_OVERVIEW_EAGER_MISS = Counter(
    "web_overview_eager_precompute_miss_total",
    "Eager read-only miss (no precomputed jobs ready), falls back to lazy INSERT",
    ["team_id"],
)


# HogQL template for the precompute INSERT.
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
        {event_type_filter},
        timestamp >= ({time_window_min} - toIntervalMinute({pad_minutes})),
        timestamp < ({time_window_max} + toIntervalMinute({pad_minutes})),
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


def can_use_precomputed_path(runner: "WebOverviewQueryRunner") -> bool:
    """Gate check for both lazy and eager precompute paths.

    Returns True if this runner's query shape is compatible with the
    preaggregated table. Callers must additionally check team-specific
    settings (lazy vs eager rollout).
    """
    query = runner.query

    if not is_integer_timezone(runner.team.timezone):
        return False

    if query.conversionGoal is not None:
        return False

    if query.sampling is not None and getattr(query.sampling, "enabled", False):
        return False

    if query.modifiers and query.modifiers.sessionsV2JoinMode == "uuid":
        return False

    properties = query.properties or []
    if len(properties) > 1:
        return False
    for prop in properties:
        if not isinstance(prop, EventPropertyFilter):
            return False
        if prop.key not in SUPPORTED_USER_FILTER_KEYS:
            return False
        if prop.operator != PropertyOperator.EXACT:
            return False
        if not isinstance(prop.value, str) or not prop.value:
            return False

    date_from = runner.query_date_range.date_from()
    date_to = runner.query_date_range.date_to()
    if date_from is None or date_to is None:
        return False

    if (date_to - date_from).days > MAX_PRECOMPUTE_DAYS:
        return False

    return True


def can_use_lazy_precompute(runner: "WebOverviewQueryRunner") -> bool:
    """Gate check for the lazy (inline INSERT) precompute path."""
    enabled_team_ids = get_instance_setting("WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS") or []
    if runner.team.pk not in enabled_team_ids:
        return False
    return can_use_precomputed_path(runner)


def can_use_eager_precompute(runner: "WebOverviewQueryRunner") -> bool:
    """Gate check for the eager (Dagster pre-warmed) precompute path."""
    enabled_team_ids = get_instance_setting("WEB_ANALYTICS_EAGER_PRECOMPUTE_TEAM_IDS") or []
    if runner.team.pk not in enabled_team_ids:
        return False
    return can_use_precomputed_path(runner)


def _user_filter_expr(runner: "WebOverviewQueryRunner") -> ast.Expr:
    if not runner.query.properties:
        return ast.Constant(value=True)

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
    if not runner._test_account_filters:
        return ast.Constant(value=True)
    return property_to_expr(runner._test_account_filters, team=runner.team)


def _events_session_id_expr(runner: "WebOverviewQueryRunner") -> ast.Expr:
    return runner.events_session_property


def _build_placeholders(runner: "WebOverviewQueryRunner") -> dict[str, ast.Expr]:
    return {
        "events_session_id": _events_session_id_expr(runner),
        "event_type_filter": runner.event_type_expr,
        "user_filter": _user_filter_expr(runner),
        "test_account_filter": _test_account_filter_expr(runner),
        "pad_minutes": ast.Constant(value=SESSION_BOUNDARY_PAD_MINUTES),
    }


def ensure_web_overview_precomputed(
    runner: "WebOverviewQueryRunner",
    time_range_start: datetime,
    time_range_end: datetime,
) -> LazyComputationResult:
    """Ensure precomputed jobs exist (creating them via INSERT if needed)."""
    return ensure_precomputed(
        team=runner.team,
        insert_query=INSERT_QUERY_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
        placeholders=_build_placeholders(runner),
        query_type="web_overview_lazy_insert",
    )


def read_web_overview_if_ready(
    runner: "WebOverviewQueryRunner",
    time_range_start: datetime,
    time_range_end: datetime,
) -> LazyComputationResult:
    """Read-only lookup: returns READY jobs without triggering any INSERTs."""
    return read_precomputed_jobs_if_ready(
        team=runner.team,
        insert_query=INSERT_QUERY_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
        placeholders=_build_placeholders(runner),
    )


_READ_SQL = f"""
SELECT
    uniqMergeIf(uniq_users_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS unique_users,
    uniqMergeIf(uniq_users_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_unique_users,
    sumMergeIf(sum_pageviews_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS views,
    sumMergeIf(sum_pageviews_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_views,
    uniqMergeIf(uniq_sessions_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS sessions,
    uniqMergeIf(uniq_sessions_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_sessions,
    avgMergeIf(avg_duration_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS avg_duration,
    avgMergeIf(avg_duration_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_avg_duration,
    avgMergeIf(avg_bounce_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS bounce_rate,
    avgMergeIf(avg_bounce_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_bounce_rate
FROM {DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE()}
WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s
"""

_READ_SETTINGS = {
    "load_balancing": "in_order",
    "optimize_skip_unused_shards": 1,
}


def execute_read_query(
    *,
    team_id: int,
    job_ids: list[str],
    current_start_utc: datetime,
    current_end_utc: datetime,
    previous_start_utc: Optional[datetime],
    previous_end_utc: Optional[datetime],
) -> list:
    prev_start = previous_start_utc if previous_start_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)
    prev_end = previous_end_utc if previous_end_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)

    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type="web_overview_lazy_query")
    return sync_execute(
        _READ_SQL,
        {
            "team_id": team_id,
            "job_ids": tuple(str(jid) for jid in job_ids),
            "cur_start": current_start_utc,
            "cur_end": current_end_utc,
            "prev_start": prev_start,
            "prev_end": prev_end,
        },
        settings=_READ_SETTINGS,
        team_id=team_id,
    )


def _floor_utc_day(dt_utc: datetime) -> datetime:
    return datetime(dt_utc.year, dt_utc.month, dt_utc.day, tzinfo=UTC)


def _ceil_utc_day(dt_utc: datetime) -> datetime:
    floor = _floor_utc_day(dt_utc)
    if floor == dt_utc:
        return floor
    return floor + timedelta(days=1)


def _empty_response_row() -> list:
    return [0, None, 0, None, 0, None, 0, None, 0, None]


def _read_from_result(
    runner: "WebOverviewQueryRunner",
    result: LazyComputationResult,
    current_start_utc: datetime,
    current_end_utc: datetime,
) -> Optional[list]:
    """Execute the read SQL against ready job_ids and return the result row."""
    if not result.job_ids:
        return None

    previous_start_utc: Optional[datetime] = None
    previous_end_utc: Optional[datetime] = None
    if runner.query_compare_to_date_range is not None:
        prev_from = runner.query_compare_to_date_range.date_from()
        prev_to = runner.query_compare_to_date_range.date_to()
        if prev_from is not None and prev_to is not None:
            previous_start_utc = prev_from.astimezone(UTC)
            previous_end_utc = prev_to.astimezone(UTC)

    rows = execute_read_query(
        team_id=runner.team.pk,
        job_ids=[str(jid) for jid in result.job_ids],
        current_start_utc=current_start_utc,
        current_end_utc=current_end_utc,
        previous_start_utc=previous_start_utc,
        previous_end_utc=previous_end_utc,
    )
    if not rows:
        return _empty_response_row()
    return list(rows[0])


def _compute_utc_bounds(
    runner: "WebOverviewQueryRunner",
) -> Optional[tuple[datetime, datetime, datetime, datetime]]:
    """Returns (current_start_utc, current_end_utc, time_range_start, time_range_end)."""
    date_from = runner.query_date_range.date_from()
    date_to = runner.query_date_range.date_to()
    if date_from is None or date_to is None:
        return None

    current_start_utc = date_from.astimezone(UTC)
    current_end_utc = date_to.astimezone(UTC)

    time_range_start = _floor_utc_day(current_start_utc)
    time_range_end = _ceil_utc_day(current_end_utc)

    if time_range_start >= time_range_end:
        return None

    return current_start_utc, current_end_utc, time_range_start, time_range_end


def execute_eager_precomputed_read(
    runner: "WebOverviewQueryRunner",
) -> Optional[list]:
    """Read-only first: return precomputed row if all windows are READY.

    Returns the response row if the preaggregated table has full coverage,
    or None if any window is missing (caller should fall back to lazy INSERT or raw).
    """
    try:
        bounds = _compute_utc_bounds(runner)
        if bounds is None:
            return None

        current_start_utc, current_end_utc, time_range_start, time_range_end = bounds

        result = read_web_overview_if_ready(
            runner=runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )

        if not result.ready:
            WEB_OVERVIEW_EAGER_MISS.labels(team_id=str(runner.team.pk)).inc()
            return None

        return _read_from_result(runner, result, current_start_utc, current_end_utc)
    except Exception as exc:
        WEB_OVERVIEW_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception("web_overview_eager_precompute_failed", team_id=runner.team.pk)
        return None


def execute_lazy_precomputed_read(
    runner: "WebOverviewQueryRunner",
) -> Optional[list]:
    """Orchestrate the lazy precompute + read (inline INSERT on cache miss).

    Returns the response row, or None on any failure (caller falls through to raw).
    """
    try:
        bounds = _compute_utc_bounds(runner)
        if bounds is None:
            return None

        current_start_utc, current_end_utc, time_range_start, time_range_end = bounds

        result = ensure_web_overview_precomputed(
            runner=runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )

        return _read_from_result(runner, result, current_start_utc, current_end_utc)
    except Exception as exc:
        WEB_OVERVIEW_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception("web_overview_lazy_precompute_failed", team_id=runner.team.pk)
        return None
