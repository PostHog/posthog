from typing import List
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.aggregation_operations import (
    AggregationOperations,
)
from posthog.hogql_queries.insights.trends.breakdown import Breakdown
from posthog.hogql_queries.insights.trends.utils import series_event_name
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team.team import Team
from posthog.schema import ActionsNode, EventsNode, TrendsQuery


class TrendsQueryBuilder:
    query: TrendsQuery
    team: Team
    query_date_range: QueryDateRange
    series: EventsNode | ActionsNode
    timings: HogQLTimings

    def __init__(
        self,
        trends_query: TrendsQuery,
        team: Team,
        query_date_range: QueryDateRange,
        series: EventsNode | ActionsNode,
        timings: HogQLTimings,
    ):
        self.query = trends_query
        self.team = team
        self.query_date_range = query_date_range
        self.series = series
        self.timings = timings

    def build_query(self) -> ast.SelectUnionQuery:
        date_subqueries = self._get_date_subqueries()
        event_query = self._get_events_subquery()

        date_events_union = ast.SelectUnionQuery(select_queries=[*date_subqueries, event_query])

        inner_select = self._inner_select_query(date_events_union)
        full_query = self._outer_select_query(inner_select)

        return full_query

    def _get_date_subqueries(self) -> List[ast.SelectQuery]:
        if not self._breakdown.enabled:
            return [
                parse_select(
                    """
                        SELECT
                            0 AS total,
                            dateTrunc({interval}, {date_to}) - {number_interval_period} AS day_start
                        FROM
                            numbers(
                                coalesce(dateDiff({interval}, {date_from}, {date_to}), 0)
                            )
                    """,
                    placeholders={
                        **self.query_date_range.to_placeholders(),
                    },
                ),
                parse_select(
                    """
                        SELECT
                            0 AS total,
                            {date_from} AS day_start
                    """,
                    placeholders={
                        **self.query_date_range.to_placeholders(),
                    },
                ),
            ]

        return [
            parse_select(
                """
                    SELECT
                        0 AS total,
                        ticks.day_start as day_start,
                        breakdown_value
                    FROM (
                        SELECT
                            dateTrunc({interval}, {date_to}) - {number_interval_period} AS day_start
                        FROM
                            numbers(
                                coalesce(dateDiff({interval}, {date_from}, {date_to}), 0)
                            )
                        UNION ALL
                        SELECT {date_from} AS day_start
                    ) as ticks
                    CROSS JOIN (
                        SELECT breakdown_value
                        FROM (
                            SELECT {cross_join_breakdown_values}
                        )
                        ARRAY JOIN breakdown_value as breakdown_value
                    ) as sec
                    ORDER BY breakdown_value, day_start
                """,
                placeholders={
                    **self.query_date_range.to_placeholders(),
                    **self._breakdown.placeholders(),
                },
            )
        ]

    def _get_events_subquery(self) -> ast.SelectQuery:
        default_query = parse_select(
            """
                SELECT
                    {aggregation_operation} AS total,
                    dateTrunc({interval}, timestamp) AS day_start
                FROM events AS e
                SAMPLE {sample}
                WHERE {events_filter}
                GROUP BY day_start
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "events_filter": self._events_filter(),
                "aggregation_operation": self._aggregation_operation.select_aggregation(),
                "sample": self._sample_value(),
            },
        )

        # No breakdowns and no complex series aggregation
        if not self._breakdown.enabled and not self._aggregation_operation.requires_query_orchestration():
            return default_query
        # Both breakdowns and complex series aggregation
        elif self._breakdown.enabled and self._aggregation_operation.requires_query_orchestration():
            orchestrator = self._aggregation_operation.get_query_orchestrator(
                events_where_clause=self._events_filter(),
                sample_value=self._sample_value(),
            )

            orchestrator.events_query_builder.append_select(self._breakdown.column_expr())
            orchestrator.events_query_builder.append_group_by(ast.Field(chain=["breakdown_value"]))

            orchestrator.inner_select_query_builder.append_select(ast.Field(chain=["breakdown_value"]))
            orchestrator.inner_select_query_builder.append_group_by(ast.Field(chain=["breakdown_value"]))

            orchestrator.parent_select_query_builder.append_select(ast.Field(chain=["breakdown_value"]))

            return orchestrator.build()
        # Just breakdowns
        elif self._breakdown.enabled:
            default_query.select.append(self._breakdown.column_expr())
            default_query.group_by.append(ast.Field(chain=["breakdown_value"]))

        # Just complex series aggregation
        elif self._aggregation_operation.requires_query_orchestration():
            return self._aggregation_operation.get_query_orchestrator(
                events_where_clause=self._events_filter(),
                sample_value=self._sample_value(),
            ).build()

        return default_query

    def _outer_select_query(self, inner_query: ast.SelectQuery) -> ast.SelectQuery:
        query = parse_select(
            """
                SELECT
                    groupArray(day_start) AS date,
                    groupArray(count) AS total
                FROM {inner_query}
            """,
            placeholders={"inner_query": inner_query},
        )

        if self._breakdown.enabled:
            query.select.append(ast.Field(chain=["breakdown_value"]))
            query.group_by = [ast.Field(chain=["breakdown_value"])]
            query.order_by = [ast.OrderExpr(expr=ast.Field(chain=["breakdown_value"]), order="ASC")]

        return query

    def _inner_select_query(self, inner_query: ast.SelectUnionQuery) -> ast.SelectQuery:
        query = parse_select(
            """
                SELECT
                    sum(total) AS count,
                    day_start
                FROM {inner_query}
                GROUP BY day_start
                ORDER BY day_start ASC
            """,
            placeholders={"inner_query": inner_query},
        )

        if self._breakdown.enabled:
            query.select.append(ast.Field(chain=["breakdown_value"]))
            query.group_by.append(ast.Field(chain=["breakdown_value"]))
            query.order_by.append(ast.OrderExpr(expr=ast.Field(chain=["breakdown_value"]), order="ASC"))

        return query

    def _events_filter(self) -> ast.Expr:
        series = self.series
        filters: List[ast.Expr] = []

        # Dates
        filters.extend(
            [
                parse_expr(
                    "timestamp >= {date_from}",
                    placeholders=self.query_date_range.to_placeholders(),
                ),
                parse_expr(
                    "timestamp <= {date_to}",
                    placeholders=self.query_date_range.to_placeholders(),
                ),
            ]
        )

        # Series
        if series_event_name(self.series) is not None:
            filters.append(
                parse_expr(
                    "event = {event}",
                    placeholders={"event": ast.Constant(value=series_event_name(self.series))},
                )
            )

        # Filter Test Accounts
        if (
            self.query.filterTestAccounts
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            for property in self.team.test_account_filters:
                filters.append(property_to_expr(property, self.team))

        # Properties
        if self.query.properties is not None and self.query.properties != []:
            filters.append(property_to_expr(self.query.properties, self.team))

        # Series Filters
        if series.properties is not None and series.properties != []:
            filters.append(property_to_expr(series.properties, self.team))

        # Breakdown
        if self._breakdown.enabled and not self._breakdown.is_histogram_breakdown:
            filters.append(self._breakdown.events_where_filter())

        if len(filters) == 0:
            return ast.Constant(value=True)
        elif len(filters) == 1:
            return filters[0]
        else:
            return ast.And(exprs=filters)

    def _sample_value(self) -> ast.RatioExpr:
        if self.query.samplingFactor is None:
            return ast.RatioExpr(left=ast.Constant(value=1))

        return ast.RatioExpr(left=ast.Constant(value=self.query.samplingFactor))

    @cached_property
    def _breakdown(self):
        return Breakdown(
            team=self.team,
            query=self.query,
            series=self.series,
            query_date_range=self.query_date_range,
            timings=self.timings,
        )

    @cached_property
    def _aggregation_operation(self):
        return AggregationOperations(self.series, self.query_date_range)
