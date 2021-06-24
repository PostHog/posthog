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


class ClickhouseFunnelTrendsNew(ClickhouseFunnelBase):
    def get_query(self, format_properties) -> str:
        formatted_query = ""
        max_steps = len(self._filter.entities)
        if max_steps >= 2:
            formatted_query = self.build_step_subquery(2, max_steps)
        else:
            formatted_query = super()._get_inner_event_query()

        breakdown_prop = self._get_breakdown_select_prop()  # TODO: allow breakdown
        # TODO: allow intervals other than a day
        print("!xxx\n", formatted_query, "\n!yyy")
        query = f"""
            SELECT toStartOfDay(toDateTime('{self._filter.date_from.strftime(TIMESTAMP_FORMAT)}') + day_index * 86400) AS day,
                total,
                completed,
                percentage,
                person_ids_total,
                person_ids_completed
            FROM numbers({cast(timedelta, self._filter.date_to - self._filter.date_from).days + 1}) AS day_index
            LEFT OUTER JOIN (
                SELECT day, start_step + final_step AS total, final_step AS completed, completed / total AS percentage, person_ids_total, person_ids_completed FROM (
                    SELECT day, countIf(furthest = 1) AS start_step, countIf(furthest={len(self._filter.entities)}) AS final_step, groupArray(person_id) AS person_ids_total, groupArray(person_id_completed) AS person_ids_completed FROM (
                        SELECT person_id, if(furthest = {len(self._filter.entities)-1}, person_id, NULL) AS person_id_completed, toStartOfDay(timestamp) AS day, max(steps) AS furthest FROM (
                            SELECT *, {self._get_sorting_condition(max_steps, max_steps)} AS steps FROM (
                                {formatted_query}
                            ) WHERE step_0 = 1
                        ) GROUP BY person_id, day
                    ) GROUP BY day
                ) 
            ) data
            ON data.day = day 
            ORDER BY day ASC
            SETTINGS allow_experimental_window_functions = 1
            """
        return query

    def build_step_subquery(self, level_index: int, max_steps: int):
        breakdown_prop = self._get_breakdown_prop()
        if level_index >= max_steps:
            return f"""
            SELECT 
            person_id,
            timestamp,
            {self.get_partition_cols(1, max_steps)}
            {breakdown_prop}
            FROM ({super()._get_inner_event_query()})
            """
        else:
            return f"""
            SELECT 
            person_id,
            timestamp,
            {self.get_partition_cols(level_index, max_steps)}
            {breakdown_prop}
            FROM (
                SELECT 
                person_id,
                timestamp,
                {self.get_comparison_cols(level_index, max_steps)}
                {breakdown_prop}
                FROM ({self.build_step_subquery(level_index + 1, max_steps)})
            )
            """

    def get_partition_cols(self, level_index: int, max_steps: int):
        cols: List[str] = []
        for i in range(0, max_steps):
            cols.append(f"step_{i}")
            if i < level_index:
                cols.append(f"latest_{i}")
            else:
                cols.append(
                    f"min(latest_{i}) over (PARTITION by person_id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) latest_{i}"
                )
        return ", ".join(cols)

    def get_comparison_cols(self, level_index: int, max_steps: int):
        cols: List[str] = []
        for i in range(0, max_steps):
            cols.append(f"step_{i}")
            if i < level_index:
                cols.append(f"latest_{i}")
            else:
                comparison = self._get_comparison_at_step(i, level_index)
                cols.append(f"if({comparison}, NULL, latest_{i}) as latest_{i}")
        return ", ".join(cols)

    def _get_breakdown_prop(self) -> str:
        if self._filter.breakdown:
            return ", prop"
        else:
            return ""

    def _get_comparison_at_step(self, index: int, level_index: int):
        or_statements: List[str] = []

        for i in range(level_index, index + 1):
            or_statements.append(f"latest_{i} < latest_{level_index - 1}")

        return " OR ".join(or_statements)

    def _get_sorting_condition(self, curr_index: int, max_steps: int):

        if curr_index == 1:
            return "1"

        conditions: List[str] = []
        for i in range(1, curr_index):
            conditions.append(f"latest_{i - 1} <= latest_{i }")
            conditions.append(f"latest_{i} <= latest_0 + INTERVAL {self._filter.funnel_window_days} DAY")

        return f"if({' AND '.join(conditions)}, {curr_index}, {self._get_sorting_condition(curr_index - 1, max_steps)})"

    def _get_step_times(self, max_steps: int):
        conditions: List[str] = []
        for i in range(1, max_steps):
            conditions.append(
                f"if(isNotNull(latest_{i}), dateDiff('second', toDateTime(latest_{i - 1}), toDateTime(latest_{i})), NULL) step{i-1}ToStep{i}Time"
            )

        return ", ".join(conditions)

    def _get_step_time_avgs(self, max_steps: int):
        conditions: List[str] = []
        for i in range(1, max_steps):
            conditions.append(f"avg(step{i-1}ToStep{i}Time) step{i-1}ToStep{i}Time")

        return ", ".join(conditions)
