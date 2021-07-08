from datetime import date, datetime, timedelta
from typing import Type, Union

from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase
from ee.clickhouse.queries.util import get_time_diff, get_trunc_func_ch
from posthog.constants import BREAKDOWN
from posthog.models.filters.filter import Filter
from posthog.models.team import Team

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HUMAN_READABLE_TIMESTAMP_FORMAT = "%a. %-d %b"


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

    Each time a funnel is entered by a person, they have exactly {funnel_window_days} days to go
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

    def __init__(self, filter: Filter, team: Team, funnel_order_class: Type[ClickhouseFunnelBase]) -> None:
        # TODO: allow breakdown
        if BREAKDOWN in filter._data:
            del filter._data[BREAKDOWN]

        super().__init__(filter, team)

        self.funnel_order = funnel_order_class(filter, team)

    def run(self, *args, **kwargs):
        if len(self._filter.entities) == 0:
            return []

        return self._get_ui_response(self.perform_query())

    def perform_query(self):
        return self._summarize_data(self._exec_query())

    def get_query(self, format_properties) -> str:

        steps_per_person_query = self.funnel_order.get_step_counts_without_aggregation_query()
        # expects multiple rows for same person, first event time, steps taken.
        self.params.update(self.funnel_order.params)

        num_intervals, seconds_in_interval, _ = get_time_diff(
            self._filter.interval or "day", self._filter.date_from, self._filter.date_to, team_id=self._team.pk
        )
        interval_method = get_trunc_func_ch(self._filter.interval)

        # How many steps must have been done to count for the denominator
        from_step = self._filter.funnel_from_step or 1
        # How many steps must have been done to count for the numerator
        to_step = self._filter.funnel_to_step or len(self._filter.entities)

        reached_from_step_count_condition = f"steps_completed >= {from_step}"
        reached_to_step_count_condition = f"steps_completed >= {to_step}"

        query = f"""
            SELECT
                {interval_method}(toDateTime('{self._filter.date_from.strftime(TIMESTAMP_FORMAT)}') + number * {seconds_in_interval}) AS entrance_period_start,
                reached_from_step_count,
                reached_to_step_count,
                conversion_rate
            FROM numbers({num_intervals}) AS period_offsets
            LEFT OUTER JOIN (
                SELECT
                    entrance_period_start,
                    reached_from_step_count,
                    reached_to_step_count,
                    if(reached_from_step_count > 0, round(reached_to_step_count / reached_from_step_count * 100, 2), 0) AS conversion_rate
                FROM (
                    SELECT
                        entrance_period_start,
                        countIf({reached_from_step_count_condition}) AS reached_from_step_count,
                        countIf({reached_to_step_count_condition}) AS reached_to_step_count
                    FROM (
                        SELECT
                            person_id,
                            {interval_method}(timestamp) AS entrance_period_start,
                            max(steps) AS steps_completed
                        FROM (
                            {steps_per_person_query}
                        ) GROUP BY person_id, entrance_period_start
                    ) GROUP BY entrance_period_start
                )
            ) data
            ON data.entrance_period_start = entrance_period_start
            ORDER BY entrance_period_start ASC
            SETTINGS allow_experimental_window_functions = 1"""

        return query

    def _summarize_data(self, results):
        summary = [
            {
                "timestamp": period_row[0],
                "reached_from_step_count": period_row[1],
                "reached_to_step_count": period_row[2],
                "conversion_rate": period_row[3],
                "is_period_final": self._is_period_final(period_row[0]),
            }
            for period_row in results
        ]
        return summary

    @staticmethod
    def _get_ui_response(summary):
        count = len(summary)
        data = []
        days = []
        labels = []

        for row in summary:
            data.append(row["conversion_rate"])
            days.append(row["timestamp"].strftime(HUMAN_READABLE_TIMESTAMP_FORMAT))
            labels.append(row["timestamp"].strftime(HUMAN_READABLE_TIMESTAMP_FORMAT))

        return [{"count": count, "data": data, "days": days, "labels": labels,}]

    def _is_period_final(self, timestamp: Union[datetime, date]):
        # difference between current date and timestamp greater than window
        now = datetime.utcnow().date()
        days_to_subtract = self._filter.funnel_window_days * -1
        delta = timedelta(days=days_to_subtract)
        completed_end = now + delta
        compare_timestamp = timestamp.date() if isinstance(timestamp, datetime) else timestamp
        is_final = compare_timestamp <= completed_end
        return is_final
