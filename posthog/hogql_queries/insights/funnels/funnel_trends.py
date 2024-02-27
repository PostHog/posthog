from datetime import datetime
from itertools import groupby
from typing import Any, Dict, List, Optional, Tuple
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql_queries.insights.funnels.base import FunnelBase
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.utils import get_funnel_order_class
from posthog.hogql_queries.insights.utils.utils import get_start_of_interval_hogql
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.cohort.cohort import Cohort
from posthog.queries.util import correct_result_for_sampling, get_earliest_timestamp, get_interval_func_ch


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HUMAN_READABLE_TIMESTAMP_FORMAT = "%-d-%b-%Y"


class FunnelTrends(FunnelBase):
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
        self.funnel_order = get_funnel_order_class(self.context.funnelsFilter)(context=self.context)

    def _format_results(self, results) -> List[Dict[str, Any]]:
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
                if isinstance(period_row[-1], str) or (
                    isinstance(period_row[-1], List) and all(isinstance(item, str) for item in period_row[-1])
                ):
                    serialized_result.update({"breakdown_value": (period_row[-1])})
                else:
                    serialized_result.update({"breakdown_value": Cohort.objects.get(pk=period_row[-1]).name})

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
            labels.append(timestamp.strftime(HUMAN_READABLE_TIMESTAMP_FORMAT))
        return {"count": count, "data": data, "days": days, "labels": labels}

    def get_query(self) -> ast.SelectQuery:
        team, interval, query, now = self.context.team, self.context.interval, self.context.query, self.context.now

        date_range = QueryDateRange(
            date_range=query.dateRange,
            team=team,
            interval=query.interval,
            now=now,
        )

        step_counts = self.get_step_counts_without_aggregation_query()
        # Expects multiple rows for same person, first event time, steps taken.

        (
            reached_from_step_count_condition,
            reached_to_step_count_condition,
            _,
        ) = self.get_steps_reached_conditions()
        interval_func = get_interval_func_ch(interval.value)

        if date_range.date_from() is None:
            _date_from = get_earliest_timestamp(team.pk)
        else:
            _date_from = date_range.date_from()

        breakdown_clause = self._get_breakdown_prop_expr()

        data_select: List[ast.Expr] = [
            ast.Field(chain=["entrance_period_start"]),
            parse_expr(f"countIf({reached_from_step_count_condition}) AS reached_from_step_count"),
            parse_expr(f"countIf({reached_to_step_count_condition}) AS reached_to_step_count"),
            *breakdown_clause,
        ]

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
        data_select_from = ast.JoinExpr(table=step_counts)
        data_group_by: List[ast.Expr] = [ast.Field(chain=["entrance_period_start"]), *breakdown_clause]
        data_query = ast.SelectQuery(select=data_select, select_from=data_select_from, group_by=data_group_by)

        fill_select: List[ast.Expr] = [
            ast.Alias(
                alias="entrance_period_start",
                expr=ast.ArithmeticOperation(
                    left=get_start_of_interval_hogql(interval.value, team=team, source=date_from_as_hogql),
                    right=ast.Call(name=interval_func, args=[ast.Field(chain=["number"])]),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            ),
            *([parse_expr("breakdown_value as prop")] if len(breakdown_clause) > 0 else []),
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
            array_join_op="ARRAY JOIN" if len(breakdown_clause) > 0 else None,
            array_join_list=(
                [
                    ast.Alias(
                        alias="breakdown_value",
                        expr=ast.Array(exprs=[parse_expr(str(value)) for value in self.breakdown_values]),
                        hidden=False,
                    )
                ]
                if len(breakdown_clause) > 0
                else None
            ),
        )
        fill_breakdown_join_constraint = []
        if len(breakdown_clause) > 0:
            # can only be a field here, since group_remaining is false
            breakdown_field: ast.Field = breakdown_clause[0]  # type: ignore
            fill_breakdown_join_constraint = [
                ast.CompareOperation(
                    left=ast.Field(chain=["data", *breakdown_field.chain]),
                    right=ast.Field(chain=["fill", *breakdown_field.chain]),
                    op=ast.CompareOperationOp.Eq,
                )
            ]
        fill_join = ast.JoinExpr(
            table=fill_query,
            alias="fill",
            join_type="RIGHT OUTER JOIN",
            constraint=ast.JoinConstraint(
                expr=ast.And(
                    exprs=[
                        ast.CompareOperation(
                            left=ast.Field(chain=["data", "entrance_period_start"]),
                            right=ast.Field(chain=["fill", "entrance_period_start"]),
                            op=ast.CompareOperationOp.Eq,
                        ),
                        *fill_breakdown_join_constraint,
                    ]
                )
            ),
        )

        select: List[ast.Expr] = [
            ast.Field(chain=["fill", "entrance_period_start"]),
            ast.Field(chain=["reached_from_step_count"]),
            ast.Field(chain=["reached_to_step_count"]),
            parse_expr(
                "if(reached_from_step_count > 0, round(reached_to_step_count / reached_from_step_count * 100, 2), 0) AS conversion_rate"
            ),
            *([ast.Field(chain=["fill", *breakdown_field.chain])] if len(breakdown_clause) > 0 else []),
        ]
        select_from = ast.JoinExpr(
            table=data_query,
            alias="data",
            next_join=fill_join,
        )
        order_by: List[ast.OrderExpr] = [
            ast.OrderExpr(expr=ast.Field(chain=["fill", "entrance_period_start"]), order="ASC")
        ]

        return ast.SelectQuery(
            select=select,
            select_from=select_from,
            order_by=order_by,
            limit=ast.Constant(value=1_000),  # increased limit (default 100) for hourly breakdown
        )

    def get_step_counts_without_aggregation_query(
        self, *, specific_entrance_period_start: Optional[datetime] = None
    ) -> ast.SelectQuery:
        team, interval, max_steps = self.context.team, self.context.interval, self.context.max_steps

        steps_per_person_query = self.funnel_order.get_step_counts_without_aggregation_query()

        event_select_clause: List[ast.Expr] = []
        if (
            hasattr(self.context, "actorsQuery")
            and self.context.actorsQuery is not None
            and self.context.actorsQuery.includeRecordings
        ):
            event_select_clause = self._get_matching_event_arrays(max_steps)

        breakdown_clause = self._get_breakdown_prop_expr()

        select: List[ast.Expr] = [
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
        group_by: List[ast.Expr] = [
            ast.Field(chain=["aggregation_target"]),
            ast.Field(chain=["entrance_period_start"]),
            *breakdown_clause,
        ]

        return ast.SelectQuery(select=select, select_from=select_from, where=where, group_by=group_by)

    def get_steps_reached_conditions(self) -> Tuple[str, str, str]:
        funnelsFilter, max_steps = self.context.funnelsFilter, self.context.max_steps

        # How many steps must have been done to count for the denominator of a funnel trends data point
        from_step = funnelsFilter.funnelFromStep or 0
        # How many steps must have been done to count for the numerator of a funnel trends data point
        to_step = funnelsFilter.funnelToStep or max_steps - 1

        # Those who converted OR dropped off
        reached_from_step_count_condition = f"steps_completed >= {from_step+1}"
        # Those who converted
        reached_to_step_count_condition = f"steps_completed >= {to_step+1}"
        # Those who dropped off
        did_not_reach_to_step_count_condition = f"{reached_from_step_count_condition} AND steps_completed < {to_step+1}"
        return (
            reached_from_step_count_condition,
            reached_to_step_count_condition,
            did_not_reach_to_step_count_condition,
        )
