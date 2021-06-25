from datetime import datetime, timedelta
from typing import Dict, List, Tuple, cast

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

        steps_from = 1  # How many steps must have been done to count for the denominator
        steps_to = len(self._filter.entities)  # How many steps must have been done to count for the numerator

        start_step_condition = f"steps_completed = {steps_from}"
        end_step_condition = f"steps_completed = {steps_to}"

        query = f"""
            SELECT
                {interval_method}(toDateTime('{self._filter.date_from.strftime(TIMESTAMP_FORMAT)}') + number * {seconds_in_interval}) AS period,
                total,
                completed,
                percentage,
                person_ids_total,
                person_ids_completed
            FROM numbers({num_intervals}) AS period_offsets
            LEFT OUTER JOIN (
                SELECT
                    period,
                    start_step + end_step AS total,
                    end_step AS completed,
                    completed / total AS percentage,
                    person_ids_total,
                    person_ids_completed
                FROM (
                    SELECT
                        period,
                        countIf({start_step_condition}) AS start_step,
                        countIf({end_step_condition}) AS end_step,
                        groupArray(person_id) AS person_ids_total,
                        groupArrayIf(person_id, {end_step_condition}) AS person_ids_completed
                    FROM (
                        SELECT
                            person_id,
                            {interval_method}(timestamp) AS period,
                            max(steps) AS steps_completed
                        FROM (
                            {steps_per_person_query}
                        ) GROUP BY person_id, period
                    ) GROUP BY period
                )
            ) data
            ON data.period = period
            ORDER BY period ASC
            SETTINGS allow_experimental_window_functions = 1"""

        return query

    def _summarize_data(self, results):
        summarized_results = [
            {
                "timestamp": period_row[0],
                "total": period_row[1],
                "completed_funnels": period_row[2],
                "percent_complete": period_row[3],
                "is_complete": self._determine_complete(period_row[0]),
                "cohort": period_row[4],
                "cohort_completed": period_row[5],
            }
            for period_row in results
        ]
        return summarized_results

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

    def _determine_complete(self, timestamp):
        # difference between current date and timestamp greater than window
        now = datetime.utcnow().date()
        days_to_subtract = self._filter.funnel_window_days * -1
        delta = timedelta(days=days_to_subtract)
        completed_end = now + delta
        compare_timestamp = timestamp.date() if type(timestamp) is datetime else timestamp
        is_incomplete = compare_timestamp > completed_end
        return not is_incomplete
