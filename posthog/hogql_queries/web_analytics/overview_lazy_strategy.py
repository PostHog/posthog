"""Lazy precomputation strategy for the WebOverview tile.

Single mode (`lazy`) — filter-in-hash. The INSERT bakes the query's property
filters into its WHERE clause, so the filter set is part of the AST and
therefore part of the lazy-executor cache key. Each unique filter combination
produces a separate cache row per daily window; the readback is trivial
(time_window filter only).

This trades cache hit rate for storage efficiency: dashboards with stable
filter sets get near-perfect hits after the first warm-up; ad-hoc filter
exploration churns the cache. WebOverview is a good fit because the response
is a single scalar row, so the alternative (filter-free + dimensional cache)
would store thousands of dimensional rows per day just to aggregate them back
to one row at readback time.

----------------------------------------------------------------------
KNOWN LIMITATIONS (must be addressed before enabling for production teams)
----------------------------------------------------------------------

1. ASYMMETRIC 1H CAP (data correctness).
   `_capped_precomputation_end` clips the precomputation upper bound to
   `now() - 1h` to skip in-flight sessions whose `$is_bounce` may still be
   NULL or may flip as the user navigates. The readback's period filter
   still uses `query_date_range.date_to()` (the user-requested range). For
   dashboards whose `date_to` is at or past `now`, the cache returns counts
   only up to `now - 1h`. Mitigation today: `_is_short_recent_range` (6h)
   rejects most "Last X hours" queries. Longer ranges that include "now"
   still slip through.
   See: `_capped_precomputation_end`, `_readback_period_filter`.

2. MODIFIER ↔ CACHE MISMATCH (data correctness).
   `_build_manual_insert_sql` runs the INSERT with
   `create_default_modifiers_for_team(team)` — runner-level modifiers
   (e.g. `bounceRatePageViewMode`, `sessionTableVersion`) are dropped before
   the INSERT runs, and `compute_query_hash` doesn't include modifiers.
   A query that overrides those modifiers will write cache rows under
   team-default semantics and read them back under the overridden
   semantics indefinitely. Fix requires changes outside this module.

3. SYNCHRONOUS INSERT BLOCKING DJANGO WORKERS (reliability).
   `ensure_precomputed` runs the INSERT inline on the request thread with
   a 180s outer wait + 600s per-attempt CH execution. There is no per-team
   rate limit or circuit breaker. Dashboard auto-refresh on a slow team
   can pile up worker slots quickly.
   See: `_ensure_precomputed`.

4. CONVERSION GOALS NOT SUPPORTED.
   Eligibility rejects `conversionGoal` queries — they use a different
   inner query shape (conversion_count / conversion_person_id) and would
   need a separate cache schema. Falls through to the existing
   live / Dagster preagg path.

5. BOUNCE SEMANTICS MATCH DAGSTER, NOT LIVE.
   `bounces_count_state = sumState(_toUInt64(ifNull(is_bounce, 0)))` —
   sessions with NULL `$is_bounce` count toward the bounce-rate denominator
   as non-bounces, matching `web_pre_aggregated_bounces`. The live path's
   `avg(is_bounce)` skips NULL inputs entirely. This is a pre-existing
   divergence between live and Dagster preagg; matching Dagster is the
   correct choice for consistency.
----------------------------------------------------------------------
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from posthog.schema import WebAnalyticsOverviewPrecomputationMode

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.web_analytics.pre_aggregated.properties import WEB_OVERVIEW_SUPPORTED_PROPERTIES
from posthog.models.team.extensions import get_or_create_team_extension

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)
from products.web_analytics.backend.models import TeamWebAnalyticsConfig

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner

logger = structlog.get_logger(__name__)


# TTL schedule — recent windows refresh more often, settled windows hold longer.
OVERVIEW_LAZY_TTL_SCHEDULE: dict[str, int] = {
    "0d": 15 * 60,
    "1d": 60 * 60,
    "7d": 6 * 60 * 60,
    "30d": 24 * 60 * 60,
    "default": 7 * 24 * 60 * 60,
}

# Recent-range guard: ranges <= this duration that end at "now" are rejected
# because the in-flight 1h skip would clip most of the window.
LAZY_PRECOMPUTATION_RECENT_RANGE_BUFFER = timedelta(hours=6)


class LazyPrecomputationNotReady(Exception):
    """Raised when ensure_precomputed returns ready=False so the runner falls back to live."""


# INSERT template — filter-in-hash. The {properties} placeholder is replaced
# with `property_to_expr(query.properties + test_account_filters, team)` so the
# WHERE clause is part of the AST that `compute_query_hash` hashes.
#
# Semantics mirror `web_pre_aggregated_bounces`:
# - sessions_uniq_state counts ALL sessions (NULL-bounce sessions included)
# - bounces_count_state uses ifNull(is_bounce, 0) — NULL counts as non-bounce
# - pageview_count is countIf($pageview/$screen) inside the per-session inner
# - total_session_count_state is sum(1) per session — matches Dagster preagg
#
# Bucketing correctness: WHERE filters by BOTH `events.timestamp` (sort-key
# prune) AND `events.session.$start_timestamp` (one-session-per-bucket
# semantics). Each session lands in exactly one daily window — the day its
# session started.
#
# Alias every SELECT column. The lazy executor's `_build_manual_insert_sql`
# raises ValueError on any bare `ast.Field` in `query.select`.
OVERVIEW_LAZY_INSERT_QUERY = """
SELECT
    toStartOfDay(start_timestamp) AS time_window_start,
    uniqState(person_id) AS persons_uniq_state,
    uniqState(session_id) AS sessions_uniq_state,
    sumState(_toUInt64(pageview_count)) AS pageviews_count_state,
    sumState(_toUInt64(ifNull(is_bounce, 0))) AS bounces_count_state,
    sumState(_toInt64(ifNull(session_duration, 0))) AS total_session_duration_state,
    sumState(_toUInt64(1)) AS total_session_count_state
FROM (
    SELECT
        any(events.person_id) AS person_id,
        events.session.session_id AS session_id,
        min(events.session.`$start_timestamp`) AS start_timestamp,
        countIf(events.event IN ('$pageview', '$screen')) AS pageview_count,
        any(events.session.`$session_duration`) AS session_duration,
        any(events.session.`$is_bounce`) AS is_bounce
    FROM events
    WHERE events.event IN ('$pageview', '$screen')
      AND events.timestamp >= {time_window_min}
      AND events.timestamp <  {time_window_max}
      AND events.session.`$start_timestamp` >= {time_window_min}
      AND events.session.`$start_timestamp` <  {time_window_max}
      AND {properties}
    GROUP BY events.session.session_id
)
WHERE start_timestamp IS NOT NULL
GROUP BY time_window_start
"""


def _is_short_recent_range(date_from: datetime, date_to: datetime) -> bool:
    """Mirror of WebAnalyticsPreAggregatedQueryBuilder._is_recent_relative_date_range.

    The lazy path stops at `now() - 1h` to skip in-flight sessions, so a short
    range that ends at "now" would be clipped to ~zero. Skip in that case.
    """
    return (date_to - date_from) <= LAZY_PRECOMPUTATION_RECENT_RANGE_BUFFER


def _is_eligible_for_lazy_overview(runner: WebOverviewQueryRunner) -> bool:
    """Eligibility check independent of mode selection.

    Rejects:
    - conversionGoal queries (different inner shape; not yet supported here)
    - property filters whose key isn't in `WEB_OVERVIEW_SUPPORTED_PROPERTIES`
      (would silently drop the filter at INSERT time, producing wrong results)
    - cohort filters (not representable as dimension column filters)
    - short ranges ending at "now" (1h trailing cap would clip the range)
    """
    query = runner.query
    if query.conversionGoal:
        return False

    all_props: list = list(query.properties or [])
    try:
        all_props += list(runner._test_account_filters or [])
    except AttributeError:
        pass
    for prop in all_props:
        prop_type = getattr(prop, "type", None)
        if prop_type == "cohort":
            return False
        prop_key = getattr(prop, "key", None)
        if prop_key is None or prop_key not in WEB_OVERVIEW_SUPPORTED_PROPERTIES:
            return False

    date_range = getattr(query, "dateRange", None)
    if not (date_range and getattr(date_range, "date_to", None)):
        date_from = runner.query_date_range.date_from()
        date_to = runner.query_date_range.date_to()
        if _is_short_recent_range(date_from, date_to):
            return False

    return True


def _team_lazy_enabled(team) -> bool:
    """Return True when the team has opted into WebOverview lazy precomputation.

    Reads `TeamWebAnalyticsConfig.overview_lazy_precomputation_enabled`. This is
    a Django config field on a team-extension model — not a PostHog feature
    flag — so eligibility checks don't depend on the analytics SDK being
    reachable and operators can scope rollout per team via the admin UI.
    """
    try:
        config = get_or_create_team_extension(team, TeamWebAnalyticsConfig)
    except Exception:
        logger.exception("web_analytics.overview_lazy_team_config_load_failed", team_id=team.id)
        return False
    return bool(config.overview_lazy_precomputation_enabled)


def resolve_lazy_overview_mode(
    runner: WebOverviewQueryRunner,
) -> WebAnalyticsOverviewPrecomputationMode | None:
    """Resolve which lazy mode (if any) to use for this query.

    Gate is the team config flag `overview_lazy_precomputation_enabled`. Per-query
    `overviewPrecomputationMode` only narrows from there:
    - Team off → always None (override cannot force-enable; no DoS surface).
    - Team on, override `OFF` → None (per-query bypass for debugging / A/B compare).
    - Team on, override `LAZY` or unset → LAZY.

    Returns None ⇒ runner falls back to its existing Dagster preagg / live dispatch.
    """
    if not _is_eligible_for_lazy_overview(runner):
        return None

    if not _team_lazy_enabled(runner.team):
        return None

    query_mode = runner.query.overviewPrecomputationMode
    if query_mode == WebAnalyticsOverviewPrecomputationMode.OFF:
        return None
    return WebAnalyticsOverviewPrecomputationMode.LAZY


class OverviewLazyStrategy:
    """Filter-in-hash lazy precomputation for WebOverview.

    The INSERT bakes the query's properties into the WHERE so cache rows are
    fragmented per (team, filter set). Readback is a trivial scalar
    aggregation over the rows that match the requested time window.
    """

    lazy_table: LazyComputationTable = LazyComputationTable.WEB_ANALYTICS_OVERVIEW_LAZY
    insert_query: str = OVERVIEW_LAZY_INSERT_QUERY

    def __init__(self, runner: WebOverviewQueryRunner) -> None:
        self.runner = runner

    def _union_period(self) -> tuple[datetime, datetime]:
        current_from = self.runner.query_date_range.date_from()
        current_to = self.runner.query_date_range.date_to()
        compare = self.runner.query_compare_to_date_range
        if compare:
            return (min(current_from, compare.date_from()), max(current_to, compare.date_to()))
        return (current_from, current_to)

    def _capped_precomputation_end(self, union_to: datetime) -> datetime:
        """Cap the precomputation upper bound at `now() - 1h` (in-flight session skip).

        KNOWN LIMITATION #1 (asymmetric 1h cap): readback still uses the
        user-requested `date_to`. Counts for windows past `now - 1h` are
        cached up to the cap, not the full range. See module docstring.
        """
        now_utc = datetime.now(UTC)
        skip_boundary = now_utc - timedelta(hours=1)
        if union_to.tzinfo is None:
            union_to = union_to.replace(tzinfo=UTC)
        return min(union_to, skip_boundary)

    def _ensure_precomputed(self) -> list[str]:
        union_from, union_to = self._union_period()
        capped_to = self._capped_precomputation_end(union_to)
        if capped_to <= union_from:
            raise LazyPrecomputationNotReady(
                f"lazy precomputation range too narrow after 1h trailing skip "
                f"(table={self.lazy_table.value}): {union_from} → {capped_to}"
            )
        result = ensure_precomputed(
            team=self.runner.team,
            insert_query=self.insert_query,
            time_range_start=union_from,
            time_range_end=capped_to,
            ttl_seconds=OVERVIEW_LAZY_TTL_SCHEDULE,
            table=self.lazy_table,
            placeholders={
                "properties": self._insert_properties_expr(),
            },
        )
        if not result.ready:
            raise LazyPrecomputationNotReady(
                f"lazy precomputation not ready (table={self.lazy_table.value}): {result.errors}"
            )
        return [str(jid) for jid in result.job_ids]

    def _insert_properties_expr(self) -> ast.Expr:
        """Property expression baked into the INSERT WHERE (and therefore the cache key).

        Combines query-level properties with team-level `_test_account_filters`
        so the cache is properly partitioned for teams that have
        `filterTestAccounts` toggled.
        """
        properties: list = list(self.runner.query.properties or [])
        try:
            properties += list(self.runner._test_account_filters or [])
        except AttributeError:
            pass
        if not properties:
            return ast.Constant(value=True)
        return property_to_expr(properties, self.runner.team)

    def _period_filter(self, date_from: datetime, date_to: datetime) -> ast.Expr:
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["time_window_start"]),
                    right=ast.Constant(value=date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["time_window_start"]),
                    right=ast.Constant(value=date_to),
                ),
            ]
        )

    def _current_period_filter(self) -> ast.Expr:
        return self._period_filter(
            self.runner.query_date_range.date_from(),
            self.runner.query_date_range.date_to(),
        )

    def _previous_period_filter(self) -> ast.Expr:
        compare = self.runner.query_compare_to_date_range
        if compare is None:
            return ast.Constant(value=False)
        return self._period_filter(compare.date_from(), compare.date_to())

    def build_query(self) -> ast.SelectQuery:
        """Build the readback SELECT.

        Shape matches the live `WebOverviewQueryRunner.outer_select` for the
        non-conversion-goal case: 10 scalars in (current, previous) pairs.
        The `_calculate` method reads positions 0..9 by index, so column
        ORDER matters.
        """
        with self.runner.timings.measure("overview_lazy_query"):
            union_from, union_to = self._union_period()
            job_ids = self._ensure_precomputed()
            current_filter = self._current_period_filter()
            previous_filter = self._previous_period_filter()
            # Use `nullif(divisor, 0)` so divisions by zero yield NULL → matches
            # the live `avg(...)` path which returns NaN on zero rows (which
            # `to_data` then maps to None in the response).
            query = parse_select(
                """
                SELECT
                    uniqMergeIf(persons_uniq_state, {current_period}) AS unique_users,
                    uniqMergeIf(persons_uniq_state, {previous_period}) AS previous_unique_users,
                    sumMergeIf(pageviews_count_state, {current_period}) AS total_filtered_pageview_count,
                    sumMergeIf(pageviews_count_state, {previous_period}) AS previous_total_filtered_pageview_count,
                    uniqMergeIf(sessions_uniq_state, {current_period}) AS unique_sessions,
                    uniqMergeIf(sessions_uniq_state, {previous_period}) AS previous_unique_sessions,
                    divide(
                        sumMergeIf(total_session_duration_state, {current_period}),
                        nullif(sumMergeIf(total_session_count_state, {current_period}), 0)
                    ) AS avg_duration_s,
                    divide(
                        sumMergeIf(total_session_duration_state, {previous_period}),
                        nullif(sumMergeIf(total_session_count_state, {previous_period}), 0)
                    ) AS previous_avg_duration_s,
                    divide(
                        sumMergeIf(bounces_count_state, {current_period}),
                        nullif(uniqMergeIf(sessions_uniq_state, {current_period}), 0)
                    ) AS bounce_rate,
                    divide(
                        sumMergeIf(bounces_count_state, {previous_period}),
                        nullif(uniqMergeIf(sessions_uniq_state, {previous_period}), 0)
                    ) AS previous_bounce_rate
                FROM web_analytics_overview_lazy
                WHERE team_id = {team_id}
                  AND job_id IN {job_ids}
                  AND time_window_start >= {union_from}
                  AND time_window_start <= {union_to}
                """,
                timings=self.runner.timings,
                placeholders={
                    "current_period": current_filter,
                    "previous_period": previous_filter,
                    "team_id": ast.Constant(value=self.runner.team.id),
                    "job_ids": ast.Tuple(exprs=[ast.Constant(value=jid) for jid in job_ids]),
                    "union_from": ast.Constant(value=union_from),
                    "union_to": ast.Constant(value=union_to),
                },
            )
            assert isinstance(query, ast.SelectQuery)
            return query


def get_lazy_overview_strategy(
    runner: WebOverviewQueryRunner,
    mode: WebAnalyticsOverviewPrecomputationMode,
) -> OverviewLazyStrategy:
    """Dispatch a runner + mode to its concrete strategy. Single-mode for now."""
    if mode == WebAnalyticsOverviewPrecomputationMode.LAZY:
        return OverviewLazyStrategy(runner)
    raise LazyPrecomputationNotReady(f"Lazy mode not yet implemented: {mode}")
