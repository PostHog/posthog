from typing import cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.insights.funnels import FunnelTrends
from posthog.hogql_queries.insights.utils.utils import get_start_of_interval_hogql_str, get_start_of_interval_hogql
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.queries.util import get_earliest_timestamp, get_interval_func_ch
from posthog.schema import BreakdownType, BreakdownAttributionType
from posthog.utils import DATERANGE_MAP

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HUMAN_READABLE_TIMESTAMP_FORMAT = "%-d-%b-%Y"


class FunnelTrendsUDF(FunnelTrends):
    def get_step_counts_query(self):
        max_steps = self.context.max_steps
        return self._get_step_counts_query(
            outer_select=[
                *self._get_matching_event_arrays(max_steps),
            ],
            inner_select=[
                *self._get_matching_events(max_steps),
            ],
        )

    def conversion_window_limit(self) -> int:
        return int(
            self.context.funnelWindowInterval * DATERANGE_MAP[self.context.funnelWindowIntervalUnit].total_seconds()
        )

    def get_query(self) -> ast.SelectQuery:
        if self.context.funnelsFilter.funnelOrderType == "strict":
            inner_event_query = self._get_inner_event_query_for_udf(
                entity_name="events", skip_step_filter=True, skip_entity_filter=True
            )
        else:
            inner_event_query = self._get_inner_event_query_for_udf(entity_name="events")

        default_breakdown_selector = "[]" if self._query_has_array_breakdown() else "''"

        # stores the steps as an array of integers from 1 to max_steps
        # so if the event could be step_0, step_1 or step_4, it looks like [1,2,0,0,5]

        # Each event is going to be a set of steps or it's going to be a set of exclusions. It can't be both.
        steps = ",".join([f"{i + 1} * step_{i}" for i in range(self.context.max_steps)])

        # this will error if they put in a bad exclusion
        exclusions = ""
        if getattr(self.context.funnelsFilter, "exclusions", None):
            exclusions = "".join([f",-{i + 1} * exclusion_{i}" for i in range(1, self.context.max_steps)])

        # Todo: Make this work for breakdowns
        if self.context.breakdownType == BreakdownType.COHORT:
            fn = "aggregate_funnel_cohort"
            breakdown_prop = ", prop"
        elif self._query_has_array_breakdown():
            fn = "aggregate_funnel_array_trends"
            breakdown_prop = ""
        else:
            fn = "aggregate_funnel_trends"
            breakdown_prop = ""

        prop_selector = "prop" if self.context.breakdown else default_breakdown_selector
        prop_vals = "groupUniqArray(prop)" if self.context.breakdown else f"[{default_breakdown_selector}]"

        breakdown_attribution_string = f"{self.context.breakdownAttributionType}{f'_{self.context.funnelsFilter.breakdownAttributionValue}' if self.context.breakdownAttributionType == BreakdownAttributionType.STEP else ''}"

        # debugging for development
        '''
        inner_select = parse_select(
            f"""
                    SELECT
                        {fn}(
                            {self.context.max_steps},
                            {self.conversion_window_limit()},
                            '{breakdown_attribution_string}',
                            '{self.context.funnelsFilter.funnelOrderType}',
                            {prop_vals},
                            arraySort(t -> t.1, groupArray(tuple(toFloat(timestamp), toInt({get_start_of_interval_hogql_str(self.context.interval.value, team=self.context.team, source='timestamp')}), {prop_selector}, arrayFilter((x) -> x != 0, [{steps}{exclusions}]))))
                        )
                    FROM {{inner_event_query}}
                    GROUP BY aggregation_target{breakdown_prop}
                """,
            {"inner_event_query": inner_event_query},
        )
        return inner_select
        '''

        inner_select = parse_select(
            f"""
                            SELECT
                                arrayJoin({fn}(
                                    {self.context.max_steps},
                                    {self.conversion_window_limit()},
                                    '{breakdown_attribution_string}',
                                    '{self.context.funnelsFilter.funnelOrderType}',
                                    {prop_vals},
                                    arraySort(t -> t.1, groupArray(tuple(toFloat(timestamp), {get_start_of_interval_hogql_str(self.context.interval.value, team=self.context.team, source='timestamp')}, {prop_selector}, arrayFilter((x) -> x != 0, [{steps}{exclusions}]))))
                                )) as af_tuple,
                                af_tuple.1 as entrance_period_start,
                                af_tuple.2 as success_bool
                            FROM {{inner_event_query}}
                            GROUP BY aggregation_target{breakdown_prop}
                        """,
            {"inner_event_query": inner_event_query},
        )

        conversion_rate_expr = (
            "if(reached_from_step_count > 0, round(reached_to_step_count / reached_from_step_count * 100, 2), 0)"
        )

        fill_query = self._get_fill_query()

        # need to change this to count data is not null
        s = parse_select(
            f"""
            SELECT
                fill.entrance_period_start as entrance_period_start,
                countIf(data.success_bool is not null) as reached_from_step_count,
                sum(data.success_bool) as reached_to_step_count,
                {conversion_rate_expr} as conversion_rate
            FROM
                ({{fill_query}}) as fill
            LEFT OUTER JOIN
                ({{inner_select}}) as data
            ON data.entrance_period_start = fill.entrance_period_start
            GROUP BY entrance_period_start
            ORDER BY entrance_period_start
        """,
            {"fill_query": fill_query, "inner_select": inner_select},
        )

        return cast(ast.SelectQuery, s)

    # The fill query returns all the start_interval dates in the response
    def _get_fill_query(self) -> str:
        team, interval, query, now = self.context.team, self.context.interval, self.context.query, self.context.now

        date_range = QueryDateRange(
            date_range=query.dateRange,
            team=team,
            interval=query.interval,
            now=now,
        )

        if date_range.date_from() is None:
            _date_from = get_earliest_timestamp(team.pk)
        else:
            _date_from = date_range.date_from()
        formatted_date_from = (_date_from.strftime("%Y-%m-%d %H:%M:%S"),)
        formatted_date_to = (date_range.date_to().strftime("%Y-%m-%d %H:%M:%S"),)
        date_from_as_hogql = ast.Call(
            name="assumeNotNull",
            args=[ast.Call(name="toDateTime", args=[(ast.Constant(value=formatted_date_from))])],
        )
        date_to_as_hogql = ast.Call(
            name="assumeNotNull",
            args=[ast.Call(name="toDateTime", args=[(ast.Constant(value=formatted_date_to))])],
        )
        interval_func = get_interval_func_ch(interval.value)

        fill_select: list[ast.Expr] = [
            ast.Alias(
                alias="entrance_period_start",
                expr=ast.ArithmeticOperation(
                    left=get_start_of_interval_hogql(interval.value, team=team, source=date_from_as_hogql),
                    right=ast.Call(name=interval_func, args=[ast.Field(chain=["number"])]),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            ),
        ]
        fill_select_from = ast.JoinExpr(
            table=ast.Field(chain=["numbers"]),
            table_args=[
                ast.ArithmeticOperation(
                    left=ast.Call(
                        name="dateDiff",
                        args=[
                            ast.Constant(value=interval.value),
                            get_start_of_interval_hogql(interval.value, team=team, source=date_from_as_hogql),
                            get_start_of_interval_hogql(interval.value, team=team, source=date_to_as_hogql),
                        ],
                    ),
                    right=ast.Constant(value=1),
                    op=ast.ArithmeticOperationOp.Add,
                )
            ],
            alias="period_offsets",
        )
        fill_query = ast.SelectQuery(
            select=fill_select,
            select_from=fill_select_from,
        )
        return fill_query
