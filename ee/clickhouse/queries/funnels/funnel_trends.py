from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple, Union, cast

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.funnels.base import ClickhouseFunnelBase
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnelNew
from ee.clickhouse.queries.util import format_ch_timestamp, get_time_diff, get_trunc_func_ch, parse_timestamps
from ee.clickhouse.sql.events import NULL_SQL_FUNNEL_TRENDS
from ee.clickhouse.sql.funnels.funnel_trend import FUNNEL_TREND_SQL
from ee.clickhouse.sql.person import GET_LATEST_PERSON_DISTINCT_ID_SQL

DAY_START = 0
TOTAL_COMPLETED_FUNNELS = 1
ALL_FUNNELS_ENTRIES = 2
PERSON_IDS = 3
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
HUMAN_READABLE_TIMESTAMP_FORMAT = "%a. %-d %b"


class ClickhouseFunnelTrends(ClickhouseFunnelBase):
    def run(self):
        if len(self._filter.entities) == 0:
            return []

        summary = self.perform_query()
        ui_response = self._get_ui_response(summary)
        return ui_response

    def perform_query(self):
        sql = self._configure_sql()
        results = sync_execute(sql, self.params)
        summary = self._summarize_data(results)
        return summary

    def _configure_sql(self):
        funnel_trend_null_sql = self._get_funnel_trend_null_sql()
        parsed_date_from, parsed_date_to, _ = self._get_dates()
        prop_filters, _ = self._get_filters()
        steps = self._get_steps()
        step_count = len(steps)
        interval_method = get_trunc_func_ch(self._filter.interval)

        sql = FUNNEL_TREND_SQL.format(
            team_id=self._team.pk,
            steps=", ".join(steps),
            step_count=step_count,
            filters=prop_filters.replace("uuid IN", "events.uuid IN", 1),
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            within_time=self._filter.milliseconds_from_days(self._filter.funnel_window_days),
            latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL,
            funnel_trend_null_sql=funnel_trend_null_sql,
            interval_method=interval_method,
        )
        return sql

    def _summarize_data(self, results):
        total = 0
        for result in results:
            total += result[ALL_FUNNELS_ENTRIES]

        out = []

        for result in results:
            percent_complete = round(result[TOTAL_COMPLETED_FUNNELS] / total * 100, 2)
            record = {
                "timestamp": result[DAY_START],
                "completed_funnels": result[TOTAL_COMPLETED_FUNNELS],
                "total": total,
                "percent_complete": percent_complete,
                "is_complete": self._determine_complete(result[DAY_START]),
                "cohort": result[PERSON_IDS],
            }
            out.append(record)

        return out

    @staticmethod
    def _get_ui_response(summary):
        count = len(summary)
        data = []
        days = []
        labels = []

        for row in summary:
            data.append(row["percent_complete"])
            days.append(row["timestamp"].strftime(HUMAN_READABLE_TIMESTAMP_FORMAT))
            labels.append(row["timestamp"].strftime(HUMAN_READABLE_TIMESTAMP_FORMAT))

        return [{"count": count, "data": data, "days": days, "labels": labels,}]

    def _get_funnel_trend_null_sql(self):
        interval_annotation = get_trunc_func_ch(self._filter.interval)
        num_intervals, seconds_in_interval, round_interval = get_time_diff(
            self._filter.interval or "day", self._filter.date_from, self._filter.date_to, team_id=self._team.pk
        )
        funnel_trend_null_sql = NULL_SQL_FUNNEL_TRENDS.format(
            interval=interval_annotation,
            seconds_in_interval=seconds_in_interval,
            num_intervals=num_intervals,
            date_to=self._filter.date_to.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return funnel_trend_null_sql

    def _get_dates(self):
        return parse_timestamps(filter=self._filter, table="events.", team_id=self._team.pk)

    def _get_filters(self):
        prop_filters, prop_filter_params = parse_prop_clauses(
            self._filter.properties,
            self._team.pk,
            prepend="global",
            allow_denormalized_props=True,
            filter_test_accounts=self._filter.filter_test_accounts,
        )
        self.params.update(prop_filter_params)
        return prop_filters, prop_filter_params

    def _get_steps(self):
        return [self._build_step_query(entity, index) for index, entity in enumerate(self._filter.entities)]

    def _determine_complete(self, timestamp):
        # difference between current date and timestamp greater than window
        now = datetime.utcnow().date()
        days_to_subtract = self._filter.funnel_window_days * -1
        delta = timedelta(days=days_to_subtract)
        completed_end = now + delta
        compare_timestamp = timestamp.date() if type(timestamp) is datetime else timestamp
        is_incomplete = compare_timestamp > completed_end
        return not is_incomplete

    def get_query(self, format_properties):
        pass


class ClickhouseFunnelTrendsNew(ClickhouseFunnelNew):
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
        breakdown_prop = self._get_breakdown_select_prop()  # TODO: allow breakdown
        steps_per_person_query = self._get_steps_per_person_query()
        num_intervals, seconds_in_interval, round_interval = get_time_diff(
            self._filter.interval or "day", self._filter.date_from, self._filter.date_to, team_id=self._team.pk
        )
        interval_method = get_trunc_func_ch(self._filter.interval)

        from_step = 1  # How many steps must have been done to count for the denominator
        to_step = len(self._filter.entities)  # How many steps must have been done to count for the numerator
        persons_page_size = 100  # How many persons to fetch in this query (the rest should be separately in next pages)

        reached_from_step_count_condition = f"steps_completed >= {from_step}"
        reached_to_step_count_condition = f"steps_completed >= {to_step}"

        query = f"""
            SELECT
                {interval_method}(toDateTime('{self._filter.date_from.strftime(TIMESTAMP_FORMAT)}') + number * {seconds_in_interval}) AS entrance_period_start,
                entered_count,
                completed_count,
                conversion_rate,
                person_ids_entered_initial_page,
                person_ids_completed_initial_page
            FROM numbers({num_intervals}) AS period_offsets
            LEFT OUTER JOIN (
                SELECT
                    entrance_period_start,
                    entered_count,
                    completed_count,
                    if(entered_count > 0, round(completed_count / entered_count * 100, 2), 0) AS conversion_rate,
                    person_ids_entered_initial_page,
                    person_ids_completed_initial_page
                FROM (
                    SELECT
                        entrance_period_start,
                        countIf({reached_from_step_count_condition}) AS entered_count,
                        countIf({reached_to_step_count_condition}) AS completed_count,
                        groupArray({persons_page_size})(DISTINCT person_id) AS person_ids_entered_initial_page,
                        groupArrayIf({persons_page_size})(DISTINCT person_id, {reached_to_step_count_condition}) AS person_ids_completed_initial_page
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
                "person_ids_entered": period_row[4],
                "person_ids_completed": period_row[5],
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
