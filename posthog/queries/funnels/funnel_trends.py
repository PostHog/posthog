from datetime import datetime
from itertools import groupby
from typing import Optional

from posthog.models.cohort import Cohort
from posthog.models.filters.filter import Filter
from posthog.models.team import Team
from posthog.queries.funnels.base import ClickhouseFunnelBase
from posthog.queries.funnels.utils import get_funnel_order_class
from posthog.queries.util import (
    correct_result_for_sampling,
    get_earliest_timestamp,
    get_interval_func_ch,
    get_start_of_interval_sql,
)

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HUMAN_READABLE_TIMESTAMP_FORMAT = "%-d-%b-%Y"


class ClickhouseFunnelTrends(ClickhouseFunnelBase):
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

    QUERY_TYPE = "funnel_trends"

    def __init__(self, filter: Filter, team: Team) -> None:
        super().__init__(filter, team)

        self.funnel_order = get_funnel_order_class(filter)(filter, team)

    def _exec_query(self):
        return self._summarize_data(super()._exec_query())

    def get_step_counts_without_aggregation_query(
        self, *, specific_entrance_period_start: Optional[datetime] = None
    ) -> str:
        steps_per_person_query = self.funnel_order.get_step_counts_without_aggregation_query()

        # This is used by funnel trends when we only need data for one period, e.g. person per data point
        if specific_entrance_period_start:
            self.params["entrance_period_start"] = specific_entrance_period_start.strftime(TIMESTAMP_FORMAT)

        event_select_clause = ""
        if self._filter.include_recordings:
            max_steps = len(self._filter.entities)
            event_select_clause = self._get_matching_event_arrays(max_steps)

        breakdown_clause = self._get_breakdown_prop()
        return f"""
            SELECT
                aggregation_target,
                {get_start_of_interval_sql(self._filter.interval, team=self._team)} AS entrance_period_start,
                max(steps) AS steps_completed
                {event_select_clause}
                {breakdown_clause}
            FROM (
                {steps_per_person_query}
            )
            {"WHERE toDateTime(entrance_period_start) = %(entrance_period_start)s" if specific_entrance_period_start else ""}
            GROUP BY aggregation_target, entrance_period_start {breakdown_clause}"""

    def get_query(self) -> str:
        step_counts = self.get_step_counts_without_aggregation_query()
        # Expects multiple rows for same person, first event time, steps taken.
        self.params.update(self.funnel_order.params)

        (
            reached_from_step_count_condition,
            reached_to_step_count_condition,
            _,
        ) = self.get_steps_reached_conditions()
        interval_func = get_interval_func_ch(self._filter.interval)

        if self._filter.date_from is None:
            _date_from = get_earliest_timestamp(self._team.pk)
        else:
            _date_from = self._filter.date_from

        breakdown_clause = self._get_breakdown_prop()

        self.params.update(
            {
                "formatted_date_from": _date_from.strftime("%Y-%m-%d %H:%M:%S"),
                "formatted_date_to": self._filter.date_to.strftime("%Y-%m-%d %H:%M:%S"),
                "interval": self._filter.interval,
            }
        )

        query = f"""
            SELECT
                entrance_period_start,
                reached_from_step_count,
                reached_to_step_count,
                if(reached_from_step_count > 0, round(reached_to_step_count / reached_from_step_count * 100, 2), 0) AS conversion_rate
                {breakdown_clause}
            FROM (
                SELECT
                    entrance_period_start,
                    countIf({reached_from_step_count_condition}) AS reached_from_step_count,
                    countIf({reached_to_step_count_condition}) AS reached_to_step_count
                    {breakdown_clause}
                FROM (
                    {step_counts}
                ) GROUP BY entrance_period_start {breakdown_clause}
            ) data
            RIGHT OUTER JOIN (
                SELECT
                {get_start_of_interval_sql(self._filter.interval, team=self._team, source='%(formatted_date_from)s')} + {interval_func}(number) AS entrance_period_start
                    {', breakdown_value as prop' if breakdown_clause else ''}
                FROM numbers(dateDiff(%(interval)s, {get_start_of_interval_sql(self._filter.interval, team=self._team, source='%(formatted_date_from)s')}, {get_start_of_interval_sql(self._filter.interval, team=self._team, source='%(formatted_date_to)s')}) + 1) AS period_offsets
                {'ARRAY JOIN (%(breakdown_values)s) AS breakdown_value' if breakdown_clause else ''}
            ) fill
            USING (entrance_period_start {breakdown_clause})
            ORDER BY entrance_period_start ASC
        """

        return query

    def get_steps_reached_conditions(self) -> tuple[str, str, str]:
        # How many steps must have been done to count for the denominator of a funnel trends data point
        from_step = self._filter.funnel_from_step or 0
        # How many steps must have been done to count for the numerator of a funnel trends data point
        to_step = self._filter.funnel_to_step or len(self._filter.entities) - 1

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

    def _summarize_data(self, results):
        breakdown_clause = self._get_breakdown_prop()

        summary = []

        for period_row in results:
            serialized_result = {
                "timestamp": period_row[0],
                "reached_from_step_count": correct_result_for_sampling(period_row[1], self._filter.sampling_factor),
                "reached_to_step_count": correct_result_for_sampling(period_row[2], self._filter.sampling_factor),
                "conversion_rate": period_row[3],
            }

            if breakdown_clause:
                if isinstance(period_row[-1], str) or (
                    isinstance(period_row[-1], list) and all(isinstance(item, str) for item in period_row[-1])
                ):
                    serialized_result.update({"breakdown_value": (period_row[-1])})
                else:
                    serialized_result.update({"breakdown_value": Cohort.objects.get(pk=period_row[-1]).name})

            summary.append(serialized_result)
        return summary

    def _format_results(self, summary):
        if self._filter.breakdown:
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
        count = len(summary)
        data = []
        days = []
        labels = []
        for row in summary:
            timestamp: datetime = row["timestamp"]
            data.append(row["conversion_rate"])
            hour_min_sec = " %H:%M:%S" if self._filter.interval == "hour" else ""
            days.append(timestamp.strftime(f"%Y-%m-%d{hour_min_sec}"))
            labels.append(timestamp.strftime(HUMAN_READABLE_TIMESTAMP_FORMAT))
        return {"count": count, "data": data, "days": days, "labels": labels}
