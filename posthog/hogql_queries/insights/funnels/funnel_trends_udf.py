from typing import Optional, cast

from rest_framework.exceptions import ValidationError

from posthog.schema import BreakdownAttributionType, BreakdownType

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.insights.funnels import FunnelTrends
from posthog.hogql_queries.insights.funnels.base import JOIN_ALGOS
from posthog.hogql_queries.insights.funnels.funnel_udf import FunnelUDFMixin
from posthog.hogql_queries.insights.utils.utils import get_start_of_interval_hogql_str
from posthog.utils import DATERANGE_MAP, relative_date_parse

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HUMAN_READABLE_TIMESTAMP_FORMAT = "%-d-%b-%Y"


class FunnelTrendsUDF(FunnelUDFMixin, FunnelTrends):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # In base, these fields only get added if you're running an actors query
        if "uuid" not in self._extra_event_fields:
            self._extra_event_fields.append("uuid")

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

    def matched_event_select(self):
        if self._include_matched_events():
            return """
                groupArray(tuple(timestamp, uuid, $session_id, $window_id)) as user_events,
                mapFromArrays(arrayMap(x -> x.2, user_events), user_events) as user_events_map,
                [user_events_map[af_tuple.4]] as matching_events,
                """
        return ""

    # This is the function that calls the UDF
    # This is used by both the query itself and the actors query
    def _inner_aggregation_query(self):
        funnelsFilter = self.context.funnelsFilter
        max_steps = self.context.max_steps
        self.context.max_steps_override = max_steps

        if self.context.funnelsFilter.funnelOrderType == "strict":
            inner_event_query = self._get_inner_event_query_for_udf(
                entity_name="events", skip_step_filter=True, skip_entity_filter=True
            )
        else:
            inner_event_query = self._get_inner_event_query_for_udf(entity_name="events")

        # stores the steps as an array of integers from 1 to max_steps
        # so if the event could be step_0, step_1 or step_4, it looks like [1,2,0,0,5]

        # Each event is going to be a set of steps or it's going to be a set of exclusions. It can't be both.
        steps = ",".join([f"{i + 1} * step_{i}" for i in range(self.context.max_steps)])

        # this will error if they put in a bad exclusion
        exclusions = ""
        if getattr(self.context.funnelsFilter, "exclusions", None):
            exclusions = "".join([f",-{i + 1} * exclusion_{i}" for i in range(1, self.context.max_steps)])

        if self.context.breakdownType == BreakdownType.COHORT:
            fn = "aggregate_funnel_cohort_trends"
        elif self._query_has_array_breakdown():
            fn = "aggregate_funnel_array_trends"
        else:
            fn = "aggregate_funnel_trends"

        if not self.context.breakdown:
            prop_selector = self._default_breakdown_selector()
        elif self._query_has_array_breakdown():
            prop_selector = "arrayMap(x -> ifNull(x, ''), prop_basic)"
        else:
            prop_selector = "ifNull(prop_basic, '')"

        breakdown_attribution_string = f"{self.context.breakdownAttributionType}{f'_{self.context.funnelsFilter.breakdownAttributionValue}' if self.context.breakdownAttributionType == BreakdownAttributionType.STEP else ''}"

        from_step = (funnelsFilter.funnelFromStep or 0) + 1
        to_step = max_steps if funnelsFilter.funnelToStep is None else funnelsFilter.funnelToStep + 1

        prop_vals = self._prop_vals()

        prop_arg = "prop"
        if self._query_has_array_breakdown() and self.context.breakdownAttributionType in (
            BreakdownAttributionType.FIRST_TOUCH,
            BreakdownAttributionType.LAST_TOUCH,
        ):
            assert isinstance(self.context.breakdown, list)
            prop_arg = f"""[empty(prop) ? [{",".join(["''"] * len(self.context.breakdown))}] : prop]"""

        inner_select = cast(
            ast.SelectQuery,
            parse_select(
                f"""
            SELECT
                arraySort(t -> t.1, groupArray(tuple(
                    toFloat(timestamp),
                    _toUInt64(toDateTime({get_start_of_interval_hogql_str(self.context.interval.value, team=self.context.team, source='timestamp')})),
                    uuid,
                    {prop_selector},
                    arrayFilter((x) -> x != 0, [{steps}{exclusions}])
                ))) as events_array,
                {prop_vals} as prop,
                arrayJoin({fn}(
                    {from_step},
                    {to_step},
                    {max_steps},
                    {self.conversion_window_limit()},
                    '{breakdown_attribution_string}',
                    '{self.context.funnelsFilter.funnelOrderType}',
                    {prop_arg},
                    events_array
                )) as af_tuple,
                toTimeZone(toDateTime(_toUInt64(af_tuple.1)), '{self.context.team.timezone}') as entrance_period_start,
                af_tuple.2 as success_bool,
                af_tuple.3 as breakdown,
                {self.matched_event_select()}
                aggregation_target as aggregation_target
            FROM {{inner_event_query}}
            GROUP BY aggregation_target
        """,
                {"inner_event_query": inner_event_query},
            ),
        )
        # This is necessary so clickhouse doesn't truncate timezone information when passing datetimes to and from python
        inner_select.settings = HogQLQuerySettings(date_time_output_format="iso", date_time_input_format="best_effort")
        return inner_select

    def get_query(self) -> ast.SelectQuery:
        inner_select = self._inner_aggregation_query()

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
        s = cast(ast.SelectQuery, s)
        s.settings = HogQLQuerySettings(join_algorithm=JOIN_ALGOS)
        return s

    def _matching_events(self):
        if (
            hasattr(self.context, "actorsQuery")
            and self.context.actorsQuery is not None
            and self.context.actorsQuery.includeRecordings
        ):
            return [ast.Alias(alias="matching_events", expr=ast.Field(chain=["matching_events"]))]
        return []

    def actor_query(
        self,
        extra_fields: Optional[list[str]] = None,
    ) -> ast.SelectQuery:
        team, actorsQuery = self.context.team, self.context.actorsQuery

        if actorsQuery is None:
            raise ValidationError("No actors query present.")

        # At this time, we do not support self.dropOff (we don't use it anywhere in the frontend)
        if actorsQuery.funnelTrendsDropOff is None:
            raise ValidationError(f"Actors parameter `funnelTrendsDropOff` must be provided for funnel trends persons!")

        if actorsQuery.funnelTrendsEntrancePeriodStart is None:
            raise ValidationError(
                f"Actors parameter `funnelTrendsEntrancePeriodStart` must be provided funnel trends persons!"
            )

        entrancePeriodStart = relative_date_parse(actorsQuery.funnelTrendsEntrancePeriodStart, team.timezone_info)
        if entrancePeriodStart is None:
            raise ValidationError(
                f"Actors parameter `funnelTrendsEntrancePeriodStart` must be a valid relative date string!"
            )

        select: list[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=ast.Field(chain=["aggregation_target"])),
            *self._matching_events(),
            *([ast.Field(chain=[field]) for field in extra_fields or []]),
        ]
        select_from = ast.JoinExpr(table=self._inner_aggregation_query())

        where = ast.And(
            exprs=[
                parse_expr("success_bool != 1") if actorsQuery.funnelTrendsDropOff else parse_expr("success_bool = 1"),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=parse_expr("entrance_period_start"),
                    right=ast.Constant(value=entrancePeriodStart),
                ),
            ]
        )
        order_by = [ast.OrderExpr(expr=ast.Field(chain=["aggregation_target"]))]

        return ast.SelectQuery(
            select=select,
            select_from=select_from,
            order_by=order_by,
            where=where,
            settings=HogQLQuerySettings(join_algorithm=JOIN_ALGOS),
        )
