from datetime import date, datetime, timedelta
from typing import Union

from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnelNew
from ee.clickhouse.queries.util import get_time_diff, get_trunc_func_ch

DAY_START = 0
TOTAL_COMPLETED_FUNNELS = 1
ALL_FUNNELS_ENTRIES = 2
PERSON_IDS = 3
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HUMAN_READABLE_TIMESTAMP_FORMAT = "%a. %-d %b"


class ClickhouseFunnelTrends(ClickhouseFunnelNew):
    """
    ## Assumptions for funnel trends

    Funnel trends are a graph of conversion over time – meaning a Y ({conversion_rate}) for each X ({entrance_period}).

    ### What is {entrance_period}?

    Let's start by defining a funnel _entrance_:
    A funnel is considered entered by a user when they have performed step {from_step} and all the steps leading to it,
    _in order_ (if there are any).
    When that happens, we consider that an entrance of the part of the funnel under consideration.
    In the default case, {from_step} is the first step of the funnel, meaning entrance from the very beginning.

    Now, our time series is based on a sequence of {entrance_period}s, each starting at {entrance_period_start}
    and ending _right before the next_ {entrance_period_start}, and a person having entered the funnel
    is only counted towards a single {entrance_period}'s numbers (hich is reflected in the time series).

    ### What is {conversion_rate}?

    This time let's start by defining a funnel _completion_:
    A funnel is considered completed by a user when they have performed step {to_step} and all the steps leading to it,
    _in order_ (including of course step {from_step}), _in the funnel window_.
    When that happens, we consider that a completion of the part of the funnel under consideration.
    In the default case, {to_step} is the last step of the funnel, meaning completion up to the very end.

    Side note: a funnel window is the interval in which step {to_step} must be reached for the completion to count.
    It starts with the moment of entrance and ends exactly {funnel_window_days} days later.

    {conversion_rate} is the number of people who have completed the funnel ({completed_count})
    divided by the number of people who have entered the funnel ({entered_count}),
    taking {entrance_period} and {funnel_window_days} into account.
    If no people have enterd the funnel in the period, {conversion_rate} is zero.
    """

    def run(self, *args, **kwargs):
        if len(self._filter.entities) == 0:
            return []

        return self._get_ui_response(self.perform_query())

    def perform_query(self):
        return self._summarize_data(self._exec_query())

    def get_query(self, format_properties) -> str:
        steps_per_person_query = self._get_steps_per_person_query()
        num_intervals, seconds_in_interval, _ = get_time_diff(
            self._filter.interval or "day", self._filter.date_from, self._filter.date_to, team_id=self._team.pk
        )
        interval_method = get_trunc_func_ch(self._filter.interval)

        from_step = 1  # How many steps must have been done to count for the denominator
        to_step = len(self._filter.entities)  # How many steps must have been done to count for the numerator

        reached_from_step_count_condition = f"steps_completed >= {from_step}"
        reached_to_step_count_condition = f"steps_completed >= {to_step}"

        query = f"""
            SELECT
                {interval_method}(toDateTime('{self._filter.date_from.strftime(TIMESTAMP_FORMAT)}') + number * {seconds_in_interval}) AS entrance_period_start,
                entered_count,
                completed_count,
                conversion_rate
            FROM numbers({num_intervals}) AS period_offsets
            LEFT OUTER JOIN (
                SELECT
                    entrance_period_start,
                    entered_count,
                    completed_count,
                    if(entered_count > 0, round(completed_count / entered_count * 100, 2), 0) AS conversion_rate
                FROM (
                    SELECT
                        entrance_period_start,
                        countIf({reached_from_step_count_condition}) AS entered_count,
                        countIf({reached_to_step_count_condition}) AS completed_count
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
                "entered_count": period_row[1],
                "completed_count": period_row[2],
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
