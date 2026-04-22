from typing import TYPE_CHECKING, Optional

import posthoganalytics

from posthog.schema import WebStatsBreakdown

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner


SESSIONS_ONLY_STATS_TABLE_FEATURE_FLAG = "web-analytics-sessions-only-stats-table"


# Breakdowns whose value is fully derivable from session-scope columns and that
# don't require event-side path cleaning, host concatenation, or composite
# expression assembly. Sessions-only mode is intentionally limited to this set
# for the first cut; richer breakdowns can be added later.
_SUPPORTED_BREAKDOWNS: dict[WebStatsBreakdown, str] = {
    WebStatsBreakdown.INITIAL_CHANNEL_TYPE: "$channel_type",
    WebStatsBreakdown.INITIAL_REFERRING_DOMAIN: "$entry_referring_domain",
    WebStatsBreakdown.INITIAL_UTM_SOURCE: "$entry_utm_source",
    WebStatsBreakdown.INITIAL_UTM_CAMPAIGN: "$entry_utm_campaign",
    WebStatsBreakdown.INITIAL_UTM_MEDIUM: "$entry_utm_medium",
    WebStatsBreakdown.INITIAL_UTM_TERM: "$entry_utm_term",
    WebStatsBreakdown.INITIAL_UTM_CONTENT: "$entry_utm_content",
}


class WebStatsTableSessionsOnlyQueryBuilder:
    """Sessions-only fast path for `web_stats_table` when there are no event- or
    session-scope filters, no conversion goal, and the breakdown resolves to a
    single session-scope column.

    Like the web_overview sessions-only path, "visitors" is approximated as
    `uniq(distinct_id)` rather than the joined path's `uniq(events.person_id)`.

    Output column order matches the joined `to_main_query` result for the same
    inputs (breakdown_value, visitors_tuple, views_tuple, optional bounce_rate
    tuple) so `WebStatsTableQueryRunner._calculate` can consume the rows
    without branching on the path.
    """

    runner: "WebStatsTableQueryRunner"

    def __init__(self, runner: "WebStatsTableQueryRunner") -> None:
        self.runner = runner

    def can_run(self) -> bool:
        if self.runner.query.conversionGoal:
            return False
        if self.runner.query.includeAvgTimeOnPage:
            return False
        if self.runner.query.properties:
            return False
        if self.runner._test_account_filters:
            return False
        if self.runner.query.breakdownBy not in _SUPPORTED_BREAKDOWNS:
            return False
        return self._feature_enabled()

    def _feature_enabled(self) -> bool:
        return bool(
            posthoganalytics.feature_enabled(
                SESSIONS_ONLY_STATS_TABLE_FEATURE_FLAG,
                str(self.runner.team.id),
                groups={"organization": str(self.runner.team.organization_id)},
                group_properties={"organization": {"id": str(self.runner.team.organization_id)}},
                send_feature_flag_events=False,
            )
        )

    def get_query(self) -> ast.SelectQuery:
        breakdown_field = _SUPPORTED_BREAKDOWNS[self.runner.query.breakdownBy]

        date_from = self.runner.query_date_range.date_from_as_hogql()
        date_to = self.runner.query_date_range.date_to_as_hogql()
        prev_date_from: Optional[ast.Expr] = None
        prev_date_to: Optional[ast.Expr] = None
        has_comparison = bool(self.runner.query_compare_to_date_range)
        if has_comparison and self.runner.query_compare_to_date_range is not None:
            prev_date_from = self.runner.query_compare_to_date_range.date_from_as_hogql()
            prev_date_to = self.runner.query_compare_to_date_range.date_to_as_hogql()

        # Build tuple aliases mirroring _period_comparison_tuple from the
        # joined-path runner so column shapes line up exactly.
        select_exprs: list[ast.Expr] = [
            ast.Alias(alias="context.columns.breakdown_value", expr=ast.Field(chain=["breakdown_value"])),
            self._tuple_metric(
                "uniq", "distinct_id", "context.columns.visitors", date_from, date_to, prev_date_from, prev_date_to
            ),
            self._tuple_metric(
                "sum", "pageview_count", "context.columns.views", date_from, date_to, prev_date_from, prev_date_to
            ),
        ]
        if self.runner.query.includeBounceRate:
            select_exprs.append(
                self._tuple_metric(
                    "avg", "is_bounce", "context.columns.bounce_rate", date_from, date_to, prev_date_from, prev_date_to
                )
            )

        inner = parse_select(
            """
SELECT
    {breakdown_value} AS breakdown_value,
    distinct_id,
    `$start_timestamp` AS start_timestamp,
    `$pageview_count` AS pageview_count,
    `$is_bounce` AS is_bounce
FROM sessions
WHERE {date_window}
            """,
            placeholders={
                "breakdown_value": ast.Field(chain=[breakdown_field]),
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

        return ast.SelectQuery(
            select=select_exprs,
            select_from=ast.JoinExpr(table=inner),
            group_by=[ast.Field(chain=["context.columns.breakdown_value"])],
        )

    def _tuple_metric(
        self,
        fn: str,
        column: str,
        alias: str,
        date_from: ast.Expr,
        date_to: ast.Expr,
        prev_date_from: Optional[ast.Expr],
        prev_date_to: Optional[ast.Expr],
    ) -> ast.Alias:
        if prev_date_from is not None and prev_date_to is not None:
            previous = self._period_aggregate(fn, column, prev_date_from, prev_date_to)
        else:
            previous = ast.Constant(value=None)
        return ast.Alias(
            alias=alias,
            expr=ast.Tuple(
                exprs=[
                    self._period_aggregate(fn, column, date_from, date_to),
                    previous,
                ]
            ),
        )

    def _period_aggregate(self, fn: str, column: str, start: ast.Expr, end: ast.Expr) -> ast.Call:
        return ast.Call(
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
        )

    def _outer_date_window(
        self,
        has_comparison: bool,
        date_from: ast.Expr,
        date_to: ast.Expr,
        prev_date_from: Optional[ast.Expr],
        prev_date_to: Optional[ast.Expr],
    ) -> ast.Expr:
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
