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
)

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner

logger = structlog.get_logger(__name__)

# Bucketing the precompute hourly keeps reads correct for any whole-hour-offset
# timezone — boundaries line up exactly when the team-local window is converted
# to UTC before filtering on `time_window_start`. Half-hour-offset timezones
# (IST, Newfoundland, Nepal, etc.) are explicitly gated out below.
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

# Upper bound on the precompute span. Above this, the framework would create
# enough daily jobs that the first request burns INSERT slots for minutes.
MAX_PRECOMPUTE_DAYS = 180


WEB_OVERVIEW_LAZY_FAILED = Counter(
    "web_overview_lazy_precompute_failed_total",
    "Lazy precompute path failures, by error class",
    ["error_type"],
)


def can_use_lazy_precompute(runner: "WebOverviewQueryRunner") -> bool:
    query = runner.query

    # Gate rollout per-team via instance setting (defaults to empty list = disabled).
    # `get_instance_setting` is backed by the Constance Redis cache, so this is
    # a single Redis hit per call — cheap enough on the hot path.
    enabled_team_ids = get_instance_setting("WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS") or []
    if runner.team.pk not in enabled_team_ids:
        return False

    # Half-hour-offset timezones (IST +5:30, Newfoundland -3:30, Nepal +5:45, etc.)
    # can't be served by UTC hourly buckets without sub-hour precision. Skip them
    # rather than return wrong totals on the boundary days.
    if not is_integer_timezone(runner.team.timezone):
        return False

    if query.conversionGoal is not None:
        return False

    if query.sampling is not None and getattr(query.sampling, "enabled", False):
        return False

    # UUID session-id mode produces `uniqState(UUID)` from
    # `events.$session_id_uuid`, which fails to insert into the schema's
    # `AggregateFunction(uniq, String)` column. Gate out until the column
    # is re-typed in a follow-up.
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


def _user_filter_expr(runner: "WebOverviewQueryRunner") -> ast.Expr:
    """Build the AST expression that gets substituted into the INSERT's WHERE clause.

    The substituted AST is what `ensure_precomputed` hashes into the cache key —
    different filter values therefore become different precomputed jobs.
    """
    if not runner.query.properties:
        return ast.Constant(value=True)

    # Gate already enforces single EventPropertyFilter with $host exact + string value.
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
    if not runner._test_account_filters:
        return ast.Constant(value=True)
    return property_to_expr(runner._test_account_filters, team=runner.team)


def _events_session_id_expr(runner: "WebOverviewQueryRunner") -> ast.Expr:
    return runner.events_session_property


# HogQL template for the precompute INSERT. The lazy_computation framework
# substitutes the listed placeholders (including `time_window_min`/`time_window_max`),
# parses the result, and INSERTs into `web_overview_preaggregated`. The framework
# automatically prepends `team_id`, `job_id` and appends `expires_at` to the SELECT.
#
# We widen the event-scan window by 1 day on each side so sessions that straddle
# the job boundary still contribute all their events to the session's hourly
# bucket. The HAVING clause keeps each session attributed only to its start hour,
# so over-scan affects INSERT cost but never produces duplicate rows.
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
        timestamp >= ({time_window_min} - toIntervalDay(1)),
        timestamp < ({time_window_max} + toIntervalDay(1)),
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
        "event_type_filter": runner.event_type_expr,
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
        query_type="web_overview_lazy_insert",
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
    # Both INSERT (via `_get_insert_settings`) and SELECT route to the same replica
    # so the read sees data the INSERT just wrote.
    "load_balancing": "in_order",
    # Shard pruning: sharding key is `sipHash64(job_id)`; `job_id IN (...)` matches
    # exactly the shards we wrote to.
    "optimize_skip_unused_shards": 1,
    # Force a quorum read against ZK to guarantee freshly-INSERTed parts are visible.
    # The INSERT side uses `insert_quorum_parallel=1` so each INSERT carries its own
    # quorum reference, which the SELECT respects via this setting.
    "select_sequential_consistency": 1,
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
    """Run the precompute-read SQL via `sync_execute`.

    Bypasses HogQL so we can set `select_sequential_consistency=1` on the SELECT —
    HogQLGlobalSettings forbids extra keys, and the read query shape is stable
    enough that string parameterization is appropriate.
    """
    # Sentinel for the no-compare case: an unsatisfiable window so the *MergeIf
    # aggregates return 0 / NaN for the "previous" columns without changing shape.
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
    # 5 metric pairs (current, previous) — previous slots are None and discarded
    # downstream when compareFilter.compare is False. When compare is True, the
    # response gets fully populated from the read query, so this default is only
    # used for genuinely empty windows.
    return [0, None, 0, None, 0, None, 0, None, 0, None]


def execute_lazy_precomputed_read(
    runner: "WebOverviewQueryRunner",
) -> Optional[list]:
    """Orchestrate the lazy precompute + read. Returns the response row, or None
    on any failure (caller falls through to the v2/raw path)."""
    try:
        date_from = runner.query_date_range.date_from()
        date_to = runner.query_date_range.date_to()
        assert date_from is not None and date_to is not None

        # Convert team-tz bounds to tz-aware UTC. We keep `tzinfo` so the HogQL
        # printer doesn't fall back to host-local timezone interpretation when
        # escaping the datetime constants in the filter.
        current_start_utc = date_from.astimezone(UTC)
        current_end_utc = date_to.astimezone(UTC)

        # Expand the precompute span to UTC day boundaries so the framework's
        # daily-window jobs fully cover the team-tz request. Without this, the
        # 08:00 UTC start of "today PT" would fall outside the framework's UTC
        # day window and have no precomputed buckets to read.
        time_range_start = _floor_utc_day(current_start_utc)
        time_range_end = _ceil_utc_day(current_end_utc)

        if time_range_start >= time_range_end:
            return None

        result = ensure_web_overview_precomputed(
            runner=runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )

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
    except Exception as exc:
        WEB_OVERVIEW_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception("web_overview_lazy_precompute_failed", team_id=runner.team.pk)
        return None
