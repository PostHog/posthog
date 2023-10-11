from typing import List
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.insights.trends.breakdown_values import BreakdownValues
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team.team import Team
from posthog.schema import ActionsNode, EventsNode, TrendsQuery


class TrendsQueryBuilder:
    query: TrendsQuery
    team: Team
    query_date_range: QueryDateRange
    series: EventsNode | ActionsNode

    def __init__(
        self, trends_query: TrendsQuery, team: Team, query_date_range: QueryDateRange, series: EventsNode | ActionsNode
    ):
        self.query = trends_query
        self.team = team
        self.query_date_range = query_date_range
        self.series = series

    def build_query(self) -> ast.SelectUnionQuery:
        date_subqueries = self._get_date_subqueries()
        event_query = self._get_events_subquery()

        date_events_union = ast.SelectUnionQuery(select_queries=[*date_subqueries, event_query])

        inner_select = self._inner_select_query(date_events_union)
        full_query = self._outer_select_query(inner_select)

        return full_query

    def _get_date_subqueries(self) -> List[ast.SelectQuery]:
        if not self._breakdown_enabled():
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
                            SELECT {breakdown_values}
                        )
                        ARRAY JOIN breakdown_value as breakdown_value
                    ) as sec
                    ORDER BY breakdown_value, day_start
                """,
                placeholders={
                    **self.query_date_range.to_placeholders(),
                    "breakdown_values": ast.Alias(alias="breakdown_value", expr=self._get_breakdown_values_ast),
                },
            )
        ]

    def _get_events_subquery(self) -> ast.SelectQuery:
        query = parse_select(
            """
                SELECT
                    {aggregation_operation} AS total,
                    dateTrunc({interval}, toTimeZone(toDateTime(timestamp), 'UTC')) AS day_start
                FROM events AS e
                %s
                WHERE {events_filter}
                GROUP BY day_start
            """
            % (self._sample_value()),
            placeholders={
                **self.query_date_range.to_placeholders(),
                "events_filter": self._events_filter(),
                "aggregation_operation": self._aggregation_operation(),
            },
        )

        if self._breakdown_enabled():
            query.select.append(
                ast.Alias(alias="breakdown_value", expr=ast.Field(chain=["properties", self.query.breakdown.breakdown]))
            )
            query.group_by.append(ast.Field(chain=["breakdown_value"]))

        return query

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

        if self._breakdown_enabled():
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

        if self._breakdown_enabled():
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
                    "(toTimeZone(timestamp, 'UTC') >= {date_from})",
                    placeholders=self.query_date_range.to_placeholders(),
                ),
                parse_expr(
                    "(toTimeZone(timestamp, 'UTC') <= {date_to})",
                    placeholders=self.query_date_range.to_placeholders(),
                ),
            ]
        )

        # Series
        if self._series_event_name() is not None:
            filters.append(
                parse_expr("event = {event}", placeholders={"event": ast.Constant(value=self._series_event_name())})
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
        if self._breakdown_enabled():
            filters.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["properties", self.query.breakdown.breakdown]),
                    op=ast.CompareOperationOp.In,
                    right=self._get_breakdown_values_ast,
                )
            )

        if len(filters) == 0:
            return ast.Constant(value=True)
        elif len(filters) == 1:
            return filters[0]
        else:
            return ast.And(exprs=filters)

    def _aggregation_operation(self) -> ast.Expr:
        if self.series.math == "hogql":
            return parse_expr(self.series.math_hogql)

        return parse_expr("count(*)")

    # Using string interpolation for SAMPLE due to HogQL limitations with `UNION ALL` and `SAMPLE` AST nodes
    def _sample_value(self) -> str:
        if self.query.samplingFactor is None:
            return ""

        return f"SAMPLE {self.query.samplingFactor}"

    def _series_event_name(self) -> str | None:
        if isinstance(self.series, EventsNode):
            return self.series.event
        return None

    def _breakdown_enabled(self):
        return self.query.breakdown is not None and self.query.breakdown.breakdown is not None

    @cached_property
    def _get_breakdown_values_ast(self) -> ast.Array:
        breakdown = BreakdownValues(
            self.team, self._series_event_name(), self.query.breakdown.breakdown, self.query_date_range
        )
        breakdown_values = breakdown.get_breakdown_values()

        return ast.Array(exprs=list(map(lambda v: ast.Constant(value=v), breakdown_values)))
