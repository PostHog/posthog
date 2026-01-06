from datetime import datetime
from itertools import groupby
from typing import Any, Optional, cast

from rest_framework.exceptions import ValidationError

from posthog.schema import BreakdownAttributionType, BreakdownType

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.insights.funnels.base import JOIN_ALGOS, FunnelBase
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.funnel_udf import FunnelUDF, FunnelUDFMixin
from posthog.hogql_queries.insights.utils.utils import get_start_of_interval_hogql, get_start_of_interval_hogql_str
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.timestamp_utils import format_label_date
from posthog.models.cohort.cohort import Cohort
from posthog.queries.util import correct_result_for_sampling, get_earliest_timestamp, get_interval_func_ch
from posthog.utils import DATERANGE_MAP, relative_date_parse


class FunnelTrendsUDF(FunnelUDFMixin, FunnelBase):
    """
    ## Funnel trends assumptions

    Funnel trends are a graph of conversion over time – meaning a Y ({conversion_rate}) for each X ({entrance_period}).

    ### What is {entrance_period}?

    A funnel is considered entered by a user when they have performed its first step.
    When that happens, we consider that an entrance of funnel.

    Now, our time series is based on a sequence of {entrance_period}s, each starting at {entrance_period_start}
    and ending _right before the next_ {entrance_period_start}. A person is then counted at most once in each
    {entrance_period}.

    ### What is {conversion_rate}?

    Each time a funnel is entered by a person, they have exactly {funnel_window_interval} {funnel_window_interval_unit} to go
    through the funnel's steps. Later events are just not taken into account.

    For {conversion_rate}, we need to know reference steps: {from_step} and {to_step}.
    By default they are respectively the first and the last steps of the funnel.

    Then for each {entrance_period} we calculate {reached_from_step_count} – the number of persons
    who entered the funnel and reached step {from_step} (along with all the steps leading up to it, if there any).
    Similarly we calculate {reached_to_step_count}, which is the number of persons from {reached_from_step_count}
    who also reached step {to_step} (along with all the steps leading up to it, including of course step {from_step}).

    {conversion_rate} is simply {reached_to_step_count} divided by {reached_from_step_count},
    multiplied by 100 to be a percentage.

    If no people have reached step {from_step} in the period, {conversion_rate} is zero.
    """

    just_summarize = False

    def __init__(self, context: FunnelQueryContext, just_summarize=False):
        super().__init__(context)

        self.just_summarize = just_summarize
        self.funnel_order = FunnelUDF(context=self.context)

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
            inner_event_query = self._get_inner_event_query(skip_step_filter=True, skip_entity_filter=True)
        else:
            inner_event_query = self._get_inner_event_query()

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

    def _format_results(self, results) -> list[dict[str, Any]]:
        query = self.context.query

        breakdown_clause = self._get_breakdown_prop()

        summary = []

        for period_row in results:
            serialized_result = {
                "timestamp": period_row[0],
                "reached_from_step_count": correct_result_for_sampling(period_row[1], query.samplingFactor),
                "reached_to_step_count": correct_result_for_sampling(period_row[2], query.samplingFactor),
                "conversion_rate": period_row[3],
            }

            if breakdown_clause:
                breakdown_value = period_row[-1]
                if breakdown_value in (None, [None], 0):
                    serialized_result.update({"breakdown_value": ["None"]})
                elif isinstance(breakdown_value, str) or (
                    isinstance(breakdown_value, list) and all(isinstance(item, str) for item in breakdown_value)
                ):
                    serialized_result.update({"breakdown_value": (breakdown_value)})
                else:
                    serialized_result.update({"breakdown_value": Cohort.objects.get(pk=breakdown_value).name})

            summary.append(serialized_result)

        if self.just_summarize is False:
            return self._format_summarized_results(summary)
        return summary

    def _format_summarized_results(self, summary):
        breakdown = self.context.breakdown

        if breakdown:
            grouper = lambda row: row["breakdown_value"]
            sorted_data = sorted(summary, key=grouper)
            final_res = []
            for key, value in groupby(sorted_data, grouper):
                breakdown_res = self._format_single_summary(list(value))
                final_res.append({**breakdown_res, "breakdown_value": key})
            return final_res
        else:
            res = self._format_single_summary(summary)

            return [res]

    def _format_single_summary(self, summary):
        interval = self.context.interval

        count = len(summary)
        data = []
        days = []
        labels = []
        for row in summary:
            timestamp: datetime = row["timestamp"]
            data.append(row["conversion_rate"])
            hour_min_sec = " %H:%M:%S" if interval.value == "hour" else ""
            days.append(timestamp.strftime(f"%Y-%m-%d{hour_min_sec}"))
            labels.append(format_label_date(timestamp, self._date_range(), self.context.team.week_start_day))
        return {"count": count, "data": data, "days": days, "labels": labels}

    def _date_range(self):
        return QueryDateRange(
            date_range=self.context.query.dateRange,
            team=self.context.team,
            interval=self.context.query.interval,
            now=self.context.now,
        )

    # The fill query returns all the start_interval dates in the response
    def _get_fill_query(self) -> ast.SelectQuery:
        team, interval = self.context.team, self.context.interval

        date_range = self._date_range()

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

    def get_step_counts_without_aggregation_query(
        self, *, specific_entrance_period_start: Optional[datetime] = None
    ) -> ast.SelectQuery:
        team, interval, max_steps = self.context.team, self.context.interval, self.context.max_steps

        steps_per_person_query = self.funnel_order.get_step_counts_without_aggregation_query()

        event_select_clause: list[ast.Expr] = []
        if (
            hasattr(self.context, "actorsQuery")
            and self.context.actorsQuery is not None
            and self.context.actorsQuery.includeRecordings
        ):
            event_select_clause = self._get_matching_event_arrays(max_steps)

        breakdown_clause = self._get_breakdown_prop_expr()

        select: list[ast.Expr] = [
            ast.Field(chain=["aggregation_target"]),
            ast.Alias(alias="entrance_period_start", expr=get_start_of_interval_hogql(interval.value, team=team)),
            parse_expr("max(steps) AS steps_completed"),
            *event_select_clause,
            *breakdown_clause,
        ]
        select_from = ast.JoinExpr(table=steps_per_person_query)
        # This is used by funnel trends when we only need data for one period, e.g. person per data point
        where = (
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=parse_expr("entrance_period_start"),
                right=ast.Constant(value=specific_entrance_period_start),
            )
            if specific_entrance_period_start
            else None
        )
        group_by: list[ast.Expr] = [
            ast.Field(chain=["aggregation_target"]),
            ast.Field(chain=["entrance_period_start"]),
            *breakdown_clause,
        ]

        return ast.SelectQuery(select=select, select_from=select_from, where=where, group_by=group_by)
