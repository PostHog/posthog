from datetime import timedelta
from math import ceil
from typing import Any, Optional, cast

from django.utils.timezone import now

from posthog.schema import (
    ActionsNode,
    CachedStickinessQueryResponse,
    DataWarehouseNode,
    EventsNode,
    HogQLQueryModifiers,
    StickinessComputationMode,
    StickinessQuery,
    StickinessQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings

from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models import Team
from posthog.models.action.action import Action
from posthog.models.cohort.util import get_count_operator, get_count_operator_ast
from posthog.models.filters.mixins.utils import cached_property


class SeriesWithExtras:
    series: EventsNode | ActionsNode | DataWarehouseNode
    series_order: int
    is_previous_period_series: Optional[bool]

    def __init__(
        self,
        series: EventsNode | ActionsNode | DataWarehouseNode,
        series_order: int,
        is_previous_period_series: Optional[bool],
    ):
        self.series = series
        self.series_order = series_order
        self.is_previous_period_series = is_previous_period_series


class StickinessQueryRunner(AnalyticsQueryRunner[StickinessQueryResponse]):
    query: StickinessQuery
    cached_response: CachedStickinessQueryResponse
    series: list[SeriesWithExtras]

    def __init__(
        self,
        query: StickinessQuery | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)
        self.series = self.setup_series()

    def _refresh_frequency(self):
        date_to = self.query_date_range.date_to()
        date_from = self.query_date_range.date_from()
        interval = self.query_date_range.interval_name

        delta_days: Optional[int] = None
        if date_from and date_to:
            delta = date_to - date_from
            delta_days = ceil(delta.total_seconds() / timedelta(days=1).total_seconds())

        refresh_frequency = BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL
        if interval == "hour" or (delta_days is not None and delta_days <= 7):
            # The interval is shorter for short-term insights
            refresh_frequency = REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL

        return refresh_frequency

    def _aggregation_expressions(self, series: EventsNode | ActionsNode | DataWarehouseNode) -> ast.Expr:
        if series.math == "hogql" and series.math_hogql is not None:
            return parse_expr(series.math_hogql)
        elif series.math == "unique_group" and series.math_group_type_index is not None:
            return ast.Field(chain=["e", f"$group_{int(series.math_group_type_index)}"])

        return ast.Field(chain=["e", "person_id"])

    def _having_clause(self) -> ast.Expr:
        if not (self.query.stickinessFilter and self.query.stickinessFilter.stickinessCriteria):
            return parse_expr("count() > 0")
        operator = self.query.stickinessFilter.stickinessCriteria.operator
        value = ast.Constant(value=self.query.stickinessFilter.stickinessCriteria.value)
        return parse_expr(f"""count() {get_count_operator(operator)} {{value}}""", {"value": value})

    def date_to_start_of_interval_hogql(self, date: ast.Expr) -> ast.Expr:
        if self.query.intervalCount is None:
            return self.query_date_range.date_to_start_of_interval_hogql(ast.Field(chain=["e", "timestamp"]))

        # find the number of intervals back from the end date
        age = parse_expr(
            """age({interval_name}, {from_date}, {to_date})""",
            placeholders={
                "interval_name": ast.Constant(value=self.query_date_range.interval_name),
                "from_date": date,
                "to_date": self.query_date_range.date_to_as_hogql(),
            },
        )
        if self.query.intervalCount == 1:
            return age

        return parse_expr(
            "floor({age} / {interval_count})",
            placeholders={"age": age, "interval_count": ast.Constant(value=self.query.intervalCount)},
        )

    def _events_query(self, series_with_extra: SeriesWithExtras) -> ast.SelectQuery:
        inner_query = parse_select(
            """
            SELECT
                {aggregation} as aggregation_target,
                {start_of_interval} as start_of_interval,
            FROM events e
            SAMPLE {sample}
            WHERE {where_clause}
            GROUP BY aggregation_target, start_of_interval
            HAVING {having_clause}
        """,
            {
                "aggregation": self._aggregation_expressions(series_with_extra.series),
                "start_of_interval": self.date_to_start_of_interval_hogql(ast.Field(chain=["e", "timestamp"])),
                "sample": self._sample_value(),
                "where_clause": self.where_clause(series_with_extra),
                "having_clause": self._having_clause(),
            },
        )

        middle_query = parse_select(
            """
            SELECT
                aggregation_target,
                count() as num_intervals
            FROM
                {inner_query}
            GROUP BY
                aggregation_target
        """,
            {"inner_query": inner_query},
        )

        outer_query = parse_select(
            """
            SELECT
                count(DISTINCT aggregation_target) as num_actors,
                num_intervals
            FROM
                {middle_query}
            GROUP BY num_intervals
            ORDER BY num_intervals
            """,
            {"middle_query": middle_query},
        )

        return cast(ast.SelectQuery, outer_query)

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return ast.SelectSetQuery.create_from_queries(self.to_queries(), "UNION ALL")

    def to_queries(self) -> list[ast.SelectQuery]:
        queries = []

        for series in self.series:
            date_range = self.date_range(series)

            interval_addition = ast.Call(
                name=f"toInterval{date_range.interval_name.capitalize()}",
                args=[ast.Constant(value=1)],
            )

            select_query = parse_select(
                """
                    SELECT
                        groupArray(num_actors) as counts,
                        groupArray(num_intervals) as intervals
                    FROM (
                        SELECT sum(num_actors) as num_actors, num_intervals
                        FROM (
                            SELECT 0 as num_actors, (number + 1) as num_intervals
                            FROM numbers(ceil(dateDiff({interval}, {date_from_start_of_interval}, {date_to_start_of_interval} + {interval_addition}) / {intervalCount}))
                            UNION ALL
                            {events_query}
                        )
                        GROUP BY num_intervals
                        ORDER BY num_intervals
                    )
                """,
                placeholders={
                    **date_range.to_placeholders(),
                    "interval_addition": interval_addition,
                    "events_query": self._events_query(series),
                    "intervalCount": ast.Constant(value=self.query.intervalCount or 1),
                },
            )

            queries.append(cast(ast.SelectQuery, select_query))

        return queries

    def to_actors_query(
        self, interval_num: Optional[int] = None, operator: Optional[str] = None
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        queries: list[ast.SelectQuery] = []

        for series in self.series:
            events_query = self._events_query(series)
            aggregation_alias = "actor_id"
            if series.series.math == "hogql" and series.series.math_hogql is not None:
                aggregation_alias = "actor_id"
            elif series.series.math == "unique_group" and series.series.math_group_type_index is not None:
                aggregation_alias = "group_key"
            events_query.select = [ast.Alias(alias=aggregation_alias, expr=ast.Field(chain=["aggregation_target"]))]
            events_query.group_by = None
            events_query.order_by = None

            # Scope down to the individual day
            if interval_num is not None:
                # For cumulative mode, we want actors who were active for X or more days
                if (
                    self.query.stickinessFilter
                    and self.query.stickinessFilter.computedAs == StickinessComputationMode.CUMULATIVE
                ):
                    events_query.where = ast.CompareOperation(
                        left=ast.Field(chain=["num_intervals"]),
                        op=ast.CompareOperationOp.GtEq,
                        right=ast.Constant(value=interval_num),
                    )
                else:
                    # For normal mode, use the provided operator or exact match
                    events_query.where = ast.CompareOperation(
                        left=ast.Field(chain=["num_intervals"]),
                        op=ast.CompareOperationOp.Eq if operator is None else get_count_operator_ast(operator),
                        right=ast.Constant(value=interval_num),
                    )

            queries.append(events_query)

        return ast.SelectSetQuery.create_from_queries(queries, "UNION ALL")

    def _calculate(self):
        queries = self.to_queries()

        res = []
        timings = []

        for index, query in enumerate(queries):
            response = execute_hogql_query(
                query_type="StickinessQuery",
                query=query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

            if response.timings is not None:
                timings.extend(response.timings)

            for val in response.results or []:
                series_with_extra = self.series[index]

                try:
                    series_label = self.series_event(series_with_extra.series)
                except Action.DoesNotExist:
                    # Dont append the series if the action doesnt exist
                    continue

                data = val[0]

                # Count doesn't change if we alter the data to cumulative
                count = sum(data)
                # Calculate cumulative values if requested
                if (
                    self.query.stickinessFilter
                    and self.query.stickinessFilter.computedAs == StickinessComputationMode.CUMULATIVE
                ):
                    cumulative_data = []
                    for i in range(len(data)):
                        total_for_days = sum(data[i:])
                        cumulative_data.append(total_for_days)
                    data = cumulative_data

                series_object = {
                    "count": count,
                    "data": data,
                    "days": val[1],
                    "label": "All events" if series_label is None else series_label,
                    "labels": [
                        f"{day} {self.query_date_range.interval_name}{'' if day == 1 else 's'} or more"
                        if (
                            self.query.stickinessFilter
                            and self.query.stickinessFilter.computedAs == StickinessComputationMode.CUMULATIVE
                        )
                        else f"{day} {self.query_date_range.interval_name}{'' if day == 1 else 's'}"
                        for day in val[1]
                    ],
                }

                # Add minimal action data for color consistency with trends
                series_object["action"] = {
                    "order": series_with_extra.series_order,
                    "type": "events",
                    "name": series_label or "All events",
                    "id": series_label,
                    "custom_name": series_with_extra.series.custom_name,
                }

                # Modifications for when comparing to previous period
                if self.query.compareFilter is not None and self.query.compareFilter.compare:
                    series_object["compare"] = True
                    series_object["compare_label"] = (
                        "previous" if series_with_extra.is_previous_period_series else "current"
                    )

                res.append(series_object)

        return StickinessQueryResponse(results=res, timings=timings, modifiers=self.modifiers)

    def where_clause(self, series_with_extra: SeriesWithExtras) -> ast.Expr:
        date_range = self.date_range(series_with_extra)
        series = series_with_extra.series
        filters: list[ast.Expr] = []

        # Dates
        filters.extend(
            [
                parse_expr(
                    "timestamp >= {date_from_with_adjusted_start_of_interval}",
                    placeholders=date_range.to_placeholders(),
                ),
                parse_expr(
                    "timestamp <= {date_to}",
                    placeholders=date_range.to_placeholders(),
                ),
            ]
        )

        # Series
        if isinstance(series, EventsNode) and series.event is not None:
            filters.append(
                parse_expr(
                    "event = {event}",
                    placeholders={"event": ast.Constant(value=series.event)},
                )
            )
        elif isinstance(series, ActionsNode):
            try:
                action = Action.objects.get(pk=int(series.id), team__project_id=self.team.project_id)
                filters.append(action_to_expr(action))
            except Action.DoesNotExist:
                # If an action doesn't exist, we want to return no events
                filters.append(parse_expr("1 = 2"))

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

        # Ignore empty groups
        if series.math == "unique_group" and series.math_group_type_index is not None:
            filters.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["e", f"$group_{int(series.math_group_type_index)}"]),
                    right=ast.Constant(value=""),
                )
            )

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

    def series_event(self, series: EventsNode | ActionsNode | DataWarehouseNode) -> str | None:
        if isinstance(series, EventsNode):
            return series.event

        if isinstance(series, DataWarehouseNode):
            return series.table_name

        if isinstance(series, ActionsNode):
            # TODO: Can we load the Action in more efficiently?
            action = Action.objects.get(pk=int(series.id), team__project_id=self.team.project_id)
            return action.name

    def intervals_num(self):
        delta = self.query_date_range.date_to() - self.query_date_range.date_from()
        if self.query_date_range.interval_name == "day":
            return delta.days + 1
        else:
            return delta.days

    def setup_series(self) -> list[SeriesWithExtras]:
        series_with_extras = [
            SeriesWithExtras(
                series,
                index,
                None,
            )
            for index, series in enumerate(self.query.series)
        ]

        if self.query.compareFilter is not None and self.query.compareFilter.compare:
            updated_series = []
            for series in series_with_extras:
                updated_series.append(
                    SeriesWithExtras(
                        series=series.series,
                        series_order=series.series_order,
                        is_previous_period_series=False,
                    )
                )
                updated_series.append(
                    SeriesWithExtras(
                        series=series.series,
                        series_order=series.series_order,
                        is_previous_period_series=True,
                    )
                )
            series_with_extras = updated_series

        return series_with_extras

    def date_range(self, series: SeriesWithExtras):
        if series.is_previous_period_series:
            return self.query_previous_date_range
        return self.query_date_range

    @property
    def exact_timerange(self):
        return self.query.dateRange and self.query.dateRange.explicitDate

    @cached_property
    def query_date_range(self):
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=now(),
            exact_timerange=self.exact_timerange,
        )

    @cached_property
    def query_previous_date_range(self):
        if self.query.compareFilter is not None and isinstance(self.query.compareFilter.compare_to, str):
            return QueryCompareToDateRange(
                date_range=self.query.dateRange,
                team=self.team,
                interval=self.query.interval,
                now=now(),
                compare_to=self.query.compareFilter.compare_to,
                exact_timerange=self.exact_timerange,
            )
        return QueryPreviousPeriodDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval,
            now=now(),
            exact_timerange=self.exact_timerange,
        )
