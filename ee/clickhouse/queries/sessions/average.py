from typing import List

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import get_time_diff, get_trunc_func_ch, parse_timestamps
from ee.clickhouse.sql.events import NULL_SQL
from ee.clickhouse.sql.sessions.average_all import AVERAGE_SQL
from ee.clickhouse.sql.sessions.average_per_period import AVERAGE_PER_PERIOD_SQL
from ee.clickhouse.sql.sessions.no_events import SESSIONS_NO_EVENTS_SQL
from posthog.models import Filter, Team
from posthog.queries.sessions.sessions import scale_time_series
from posthog.utils import append_data, friendly_time


class ClickhouseSessionsAvg:
    def calculate_avg(self, filter: Filter, team: Team):

        parsed_date_from, parsed_date_to, _ = parse_timestamps(filter, team.pk)

        filters, params = parse_prop_clauses(filter.properties, team.pk)

        interval_notation = get_trunc_func_ch(filter.interval)
        num_intervals, seconds_in_interval, _ = get_time_diff(
            filter.interval or "day", filter.date_from, filter.date_to, team.pk
        )

        avg_query = SESSIONS_NO_EVENTS_SQL.format(
            team_id=team.pk, date_from=parsed_date_from, date_to=parsed_date_to, filters=filters, sessions_limit="",
        )
        per_period_query = AVERAGE_PER_PERIOD_SQL.format(sessions=avg_query, interval=interval_notation)

        null_sql = NULL_SQL.format(
            date_to=filter.date_to.strftime("%Y-%m-%d 00:00:00"),
            interval=interval_notation,
            num_intervals=num_intervals,
            seconds_in_interval=seconds_in_interval,
        )

        final_query = AVERAGE_SQL.format(sessions=per_period_query, null_sql=null_sql)

        params = {**params, "team_id": team.pk}
        response = sync_execute(final_query, params)
        values = self.clean_values(filter, response)
        time_series_data = append_data(values, interval=filter.interval, math=None)
        scaled_data, _ = scale_time_series(time_series_data["data"])
        time_series_data.update({"data": scaled_data})
        # calculate average
        total = sum(val[1] for val in values)

        if total == 0:
            return []

        valid_days = sum(1 if val[1] else 0 for val in values)
        overall_average = (total / valid_days) if valid_days else 0

        result = self._format_avg(overall_average)
        time_series_data.update(result)

        return [time_series_data]

    def clean_values(self, filter: Filter, values: List) -> List:
        if filter.interval == "month":
            return [(item[1] + relativedelta(months=1, days=-1), item[0]) for item in values]
        else:
            return [(item[1], item[0]) for item in values]

    def _format_avg(self, avg: float):
        avg_formatted = friendly_time(avg)
        avg_split = avg_formatted.split(" ")
        time_series_data = {}
        time_series_data.update(
            {"label": "Average Session Length ({})".format(avg_split[1]), "count": int(avg_split[0]),}
        )
        time_series_data.update({"chartLabel": "Average Session Length ({})".format(avg_split[1])})
        return time_series_data
