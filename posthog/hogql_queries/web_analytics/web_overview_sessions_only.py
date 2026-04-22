from typing import TYPE_CHECKING, Optional

import posthoganalytics

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner


SESSIONS_ONLY_OVERVIEW_FEATURE_FLAG = "web-analytics-sessions-only-overview"


class WebOverviewSessionsOnlyQueryBuilder:
    """Sessions-only fast path for `web_overview` when there are no event- or
    session-scope filters and no conversion goal.

    Skips the events↔sessions LEFT JOIN entirely and reads metrics directly
    from the sessions table:

    - unique sessions, pageviews, bounce rate, session duration come from the
      per-session aggregate state already materialized into `raw_sessions`.
    - "visitors" is approximated as `uniq(distinct_id)` rather than the joined
      path's `uniq(events.person_id)`. For PostHog web analytics — anonymous
      traffic dominates and each anonymous distinct_id ≈ one person — the
      drift is small. The proxy is documented and rolled out behind a feature
      flag so we can compare against the joined path on real traffic before
      defaulting to it.

    Output column order is identical to the joined `web_overview` path so the
    calling runner can consume rows by index without a branch.
    """

    runner: "WebOverviewQueryRunner"

    def __init__(self, runner: "WebOverviewQueryRunner") -> None:
        self.runner = runner

    def can_run(self) -> bool:
        if self.runner.query.conversionGoal:
            return False
        # Zero-filter case only — any filter (event- or session-scope) means we
        # need the joined path or richer per-event data the sessions table
        # doesn't carry.
        if self.runner.query.properties:
            return False
        if self.runner._test_account_filters:
            return False
        return self._feature_enabled()

    def _feature_enabled(self) -> bool:
        return bool(
            posthoganalytics.feature_enabled(
                SESSIONS_ONLY_OVERVIEW_FEATURE_FLAG,
                str(self.runner.team.id),
                groups={"organization": str(self.runner.team.organization_id)},
                group_properties={"organization": {"id": str(self.runner.team.organization_id)}},
                send_feature_flag_events=False,
            )
        )

    def get_query(self) -> ast.SelectQuery:
        has_comparison = bool(self.runner.query_compare_to_date_range)

        date_from = self.runner.query_date_range.date_from_as_hogql()
        date_to = self.runner.query_date_range.date_to_as_hogql()
        prev_date_from: Optional[ast.Expr] = None
        prev_date_to: Optional[ast.Expr] = None
        if has_comparison and self.runner.query_compare_to_date_range is not None:
            prev_date_from = self.runner.query_compare_to_date_range.date_from_as_hogql()
            prev_date_to = self.runner.query_compare_to_date_range.date_to_as_hogql()

        select_exprs: list[ast.Expr] = []
        # Output column order MUST match the joined-path web_overview query so
        # that WebOverviewQueryRunner._calculate can index rows positionally:
        # visitors, prev, views, prev, sessions, prev, duration, prev, bounce, prev.
        for fn, column, alias in [
            ("uniq", "distinct_id", "unique_users"),
            ("sum", "pageview_and_screen_count", "total_filtered_pageview_count"),
            ("uniq", "session_id_v7", "unique_sessions"),
            ("avg", "session_duration", "avg_duration_s"),
            ("avg", "is_bounce", "bounce_rate"),
        ]:
            select_exprs.extend(
                self._metric_pair(
                    fn,
                    column,
                    alias,
                    has_comparison=has_comparison,
                    date_from=date_from,
                    date_to=date_to,
                    prev_date_from=prev_date_from,
                    prev_date_to=prev_date_to,
                )
            )

        # Wrap the sessions table so the alias `pageview_and_screen_count`
        # exists for the metric expression and the timestamp is exposed under
        # the bare name `start_timestamp` (matching the joined-path's
        # convention so the metric helpers can reference it without escaping).
        inner = parse_select(
            """
SELECT
    distinct_id,
    session_id_v7,
    `$start_timestamp` AS start_timestamp,
    `$session_duration` AS session_duration,
    `$is_bounce` AS is_bounce,
    `$pageview_count` + `$screen_count` AS pageview_and_screen_count
FROM sessions
WHERE {date_window}
            """,
            placeholders={
                "date_window": self._outer_date_window(
                    has_comparison=has_comparison,
                    date_from=date_from,
                    date_to=date_to,
                    prev_date_from=prev_date_from,
                    prev_date_to=prev_date_to,
                ),
            },
        )
        assert isinstance(inner, ast.SelectQuery)

        return ast.SelectQuery(select=select_exprs, select_from=ast.JoinExpr(table=inner))

    def _metric_pair(
        self,
        fn: str,
        column: str,
        alias: str,
        has_comparison: bool,
        date_from: ast.Expr,
        date_to: ast.Expr,
        prev_date_from: Optional[ast.Expr],
        prev_date_to: Optional[ast.Expr],
    ) -> list[ast.Expr]:
        previous_alias = f"previous_{alias}"
        current_expr = (
            self._period_aggregate(fn, column, date_from, date_to, alias)
            if has_comparison
            else ast.Alias(alias=alias, expr=ast.Call(name=fn, args=[ast.Field(chain=[column])]))
        )
        if has_comparison and prev_date_from is not None and prev_date_to is not None:
            previous_expr: ast.Expr = self._period_aggregate(fn, column, prev_date_from, prev_date_to, previous_alias)
        else:
            previous_expr = ast.Alias(alias=previous_alias, expr=ast.Constant(value=None))
        return [current_expr, previous_expr]

    def _period_aggregate(
        self,
        fn: str,
        column: str,
        start: ast.Expr,
        end: ast.Expr,
        alias: str,
    ) -> ast.Alias:
        return ast.Alias(
            alias=alias,
            expr=ast.Call(
                name=fn + "If",
                args=[
                    ast.Field(chain=[column]),
                    ast.Call(
                        name="and",
                        args=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.GtEq,
                                left=ast.Field(chain=["start_timestamp"]),
                                right=start,
                            ),
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.LtEq,
                                left=ast.Field(chain=["start_timestamp"]),
                                right=end,
                            ),
                        ],
                    ),
                ],
            ),
        )

    def _outer_date_window(
        self,
        has_comparison: bool,
        date_from: ast.Expr,
        date_to: ast.Expr,
        prev_date_from: Optional[ast.Expr],
        prev_date_to: Optional[ast.Expr],
    ) -> ast.Expr:
        # Narrow the sessions scan to the smallest window that covers both
        # current and (optional) comparison ranges, so the metric expressions
        # only filter inside an already-narrow result set. References the raw
        # sessions field `$start_timestamp` since the inner select's alias
        # isn't visible to its own WHERE clause.
        if has_comparison and prev_date_from is not None and prev_date_to is not None:
            window_from = ast.Call(name="least", args=[date_from, prev_date_from])
            window_to = ast.Call(name="greatest", args=[date_to, prev_date_to])
        else:
            window_from = date_from
            window_to = date_to
        return ast.Call(
            name="and",
            args=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["$start_timestamp"]),
                    right=window_from,
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["$start_timestamp"]),
                    right=window_to,
                ),
            ],
        )
