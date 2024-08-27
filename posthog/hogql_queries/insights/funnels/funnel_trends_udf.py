from typing import cast

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.insights.funnels import FunnelTrends
from posthog.hogql_queries.insights.utils.utils import get_start_of_interval_hogql_str
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
        # If they're asking for a "to_step" just truncate the funnel
        funnelsFilter = self.context.funnelsFilter
        max_steps = self.context.max_steps if funnelsFilter.funnelToStep is None else funnelsFilter.funnelToStep + 1
        self.context.max_steps_override = max_steps

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
            fn = "aggregate_funnel_cohort_trends"
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

        from_step = funnelsFilter.funnelFromStep or 0

        inner_select = parse_select(
            f"""
            SELECT
                arrayJoin({fn}(
                    {from_step},
                    {max_steps},
                    {self.conversion_window_limit()},
                    '{breakdown_attribution_string}',
                    '{self.context.funnelsFilter.funnelOrderType}',
                    {prop_vals},
                    arraySort(t -> t.1, groupArray(tuple(toFloat(timestamp), {get_start_of_interval_hogql_str(self.context.interval.value, team=self.context.team, source='timestamp')}, {prop_selector}, arrayFilter((x) -> x != 0, [{steps}{exclusions}]))))
                )) as af_tuple,
                toTimeZone(af_tuple.1, '{self.context.team.timezone}') as entrance_period_start,
                af_tuple.2 as success_bool,
                af_tuple.3 as breakdown
            FROM {{inner_event_query}}
            GROUP BY aggregation_target{breakdown_prop}
        """,
            {"inner_event_query": inner_event_query},
        )
        # This is necessary so clickhouse doesn't truncate timezone information when passing datetimes to python
        inner_select.settings = HogQLQuerySettings(date_time_output_format="iso", date_time_input_format="best_effort")

        conversion_rate_expr = (
            "if(reached_from_step_count > 0, round(reached_to_step_count / reached_from_step_count * 100, 2), 0)"
        )

        fill_query = self._get_fill_query()

        limit = 1_000
        if self.context.breakdown:
            breakdown_limit = self.get_breakdown_limit()
            if breakdown_limit:
                limit = min(breakdown_limit * len(self._date_range().all_values()), limit)

            s = parse_select(
                f"""
            SELECT
                fill.entrance_period_start AS entrance_period_start,
                sumIf(data.reached_from_step_count, ifNull(equals(fill.entrance_period_start, data.entrance_period_start), isNull(fill.entrance_period_start) and isNull(data.entrance_period_start))) AS reached_from_step_count,
                sumIf(data.reached_to_step_count, ifNull(equals(fill.entrance_period_start, data.entrance_period_start), isNull(fill.entrance_period_start) and isNull(data.entrance_period_start))) AS reached_to_step_count,
                if(ifNull(greater(reached_from_step_count, 0), 0), round(multiply(divide(reached_to_step_count, reached_from_step_count), 100), 2), 0) AS conversion_rate,
                data.prop AS prop
            FROM
                ({{fill_query}}) as fill
                CROSS JOIN (SELECT
                    entrance_period_start as entrance_period_start,
                    countIf(success_bool != 0) as reached_from_step_count,
                    countIf(success_bool = 1) as reached_to_step_count,
                    breakdown as prop
                FROM
                    ({{inner_select}})
                GROUP BY entrance_period_start, breakdown) as data
            GROUP BY
                fill.entrance_period_start,
                data.prop
            ORDER BY
                sum(reached_from_step_count) OVER (PARTITION BY data.prop) DESC,
                data.prop DESC,
                fill.entrance_period_start ASC
            LIMIT {limit}
            """,
                {"fill_query": fill_query, "inner_select": inner_select},
            )
        else:
            s = parse_select(
                f"""
                SELECT
                    fill.entrance_period_start as entrance_period_start,
                    countIf(success_bool != 0) as reached_from_step_count,
                    countIf(success_bool = 1) as reached_to_step_count,
                    {conversion_rate_expr} as conversion_rate,
                    breakdown as prop
                FROM
                    ({{inner_select}}) as data
                RIGHT OUTER JOIN
                    ({{fill_query}}) as fill
                ON data.entrance_period_start = fill.entrance_period_start
                GROUP BY entrance_period_start, data.breakdown
                ORDER BY entrance_period_start
                LIMIT {limit}
            """,
                {"fill_query": fill_query, "inner_select": inner_select},
            )
        return cast(ast.SelectQuery, s)
