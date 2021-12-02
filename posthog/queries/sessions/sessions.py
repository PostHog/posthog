import datetime
from typing import Any, Dict, List, Tuple

from django.db import connection
from django.db.models import F, Q, QuerySet
from django.db.models.expressions import Window
from django.db.models.functions import Lag

from posthog.constants import SESSION_AVG
from posthog.models import Event, Filter, Team
from posthog.queries.base import (
    BaseQuery,
    convert_to_comparison,
    determine_compared_filter,
    filter_events,
    process_entity_for_events,
    properties_to_Q,
)
from posthog.utils import append_data, friendly_time, get_daterange

DIST_LABELS = [
    "0 seconds (1 event)",
    "0-3 seconds",
    "3-10 seconds",
    "10-30 seconds",
    "30-60 seconds",
    "1-3 minutes",
    "3-10 minutes",
    "10-30 minutes",
    "30-60 minutes",
    "1+ hours",
]

Query = str
QueryParams = Tuple[Any, ...]


class Sessions(BaseQuery):
    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        calculated = []

        events = Event.objects.none()
        for entity in filter.entities:
            events |= process_entity_for_events(entity, team_id=team.pk).filter(
                filter_events(team_id=team.pk, filter=filter, entity=entity, include_dates=False)
            )

        if not len(events):
            events = self.events_query(filter, team)

        # get compared period
        if filter.compare and filter._date_from != "all" and filter.session == SESSION_AVG:
            calculated = self.calculate_sessions(events.filter(filter.date_filter_Q), filter, team)
            calculated = convert_to_comparison(calculated, filter, "current")

            compare_filter = determine_compared_filter(filter)
            compared_calculated = self.calculate_sessions(
                events.filter(compare_filter.date_filter_Q), compare_filter, team
            )
            converted_compared_calculated = convert_to_comparison(compared_calculated, filter, "previous")
            calculated.extend(converted_compared_calculated)
        else:
            events = events.filter(filter.date_filter_Q)
            calculated = self.calculate_sessions(events, filter, team)

        return calculated

    def calculate_sessions(self, events: QuerySet, filter: Filter, team: Team) -> List[Dict[str, Any]]:
        all_sessions, sessions_sql_params = self.build_all_sessions_query(events)

        if filter.session == SESSION_AVG:
            if not filter.date_from:
                filter = filter.with_data(
                    {
                        "date_from": Event.objects.filter(team=team)
                        .order_by("timestamp")[0]
                        .timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                        .isoformat(),
                    }
                )
            return self._session_avg(all_sessions, sessions_sql_params, filter)
        else:  # SESSION_DIST
            return self._session_dist(all_sessions, sessions_sql_params)

    def events_query(self, filter: Filter, team: Team) -> QuerySet:
        return (
            Event.objects.filter(team=team)
            .add_person_id(team.pk)
            .filter(~Q(event="$feature_flag_called"))
            .filter(properties_to_Q(filter.properties, team_id=team.pk))
            .order_by("-timestamp")
        )

    def build_all_sessions_query(self, events: QuerySet, _date_gte=Q()) -> Tuple[Query, QueryParams]:
        sessions = events.filter(_date_gte).annotate(
            previous_timestamp=Window(
                expression=Lag("timestamp", default=None), partition_by=F("distinct_id"), order_by=F("timestamp").asc(),
            )
        )

        sessions_sql, sessions_sql_params = sessions.query.sql_with_params()
        all_sessions = """
            SELECT *,
                SUM(new_session) OVER (ORDER BY distinct_id, timestamp) AS global_session_id
                FROM (
                    SELECT
                        id, team_id, distinct_id, event, elements_hash, timestamp, properties,
                        CASE
                            WHEN EXTRACT('EPOCH' FROM (timestamp - previous_timestamp)) >= (60 * 30) OR previous_timestamp IS NULL
                            THEN 1
                            ELSE 0
                        END AS new_session
                    FROM ({}) AS inner_sessions
                ) AS outer_sessions
        """.format(
            sessions_sql
        )

        return all_sessions, sessions_sql_params

    def _session_avg(self, base_query: Query, params: QueryParams, filter: Filter) -> List[Dict[str, Any]]:
        def _determineInterval(interval):
            if interval == "minute":
                return (
                    "minute",
                    "min",
                )
            elif interval == "hour":
                return "hour", "H"
            elif interval == "week":
                return "week", "W"
            elif interval == "month":
                return "month", "M"
            else:
                return "day", "D"

        interval, interval_freq = _determineInterval(filter.interval)

        average_length_time = "SELECT date_trunc('{interval}', timestamp) as start_time,\
                        AVG(length) AS average_session_length_per_day,\
                        SUM(length) AS total_session_length_per_day, \
                        COUNT(1) as num_sessions_per_day\
                        FROM (SELECT global_session_id, EXTRACT('EPOCH' FROM (MAX(timestamp) - MIN(timestamp)))\
                            AS length,\
                            MIN(timestamp) as timestamp FROM ({}) as count GROUP BY 1) as agg group by 1 order by start_time".format(
            base_query, interval=interval
        )

        cursor = connection.cursor()
        cursor.execute(average_length_time, params)
        time_series_avg = cursor.fetchall()
        if len(time_series_avg) == 0:
            return []

        date_range = get_daterange(filter.date_from, filter.date_to, frequency=interval)
        data_array = [{"date": a[0], "count": a[1], "breakdown": "Total"} for a in time_series_avg]

        if interval == "week":
            for df in data_array:
                df["date"] -= datetime.timedelta(days=df["date"].weekday() + 1)
        elif interval == "month":
            for df in data_array:
                df["date"] = (df["date"].replace(day=1) + datetime.timedelta(days=32)).replace(
                    day=1
                ) - datetime.timedelta(days=1)
            for idx in range(len(date_range)):
                date_range[idx] = (date_range[idx].replace(day=1) + datetime.timedelta(days=32)).replace(
                    day=1
                ) - datetime.timedelta(days=1)

        datewise_data = {d["date"]: d["count"] for d in data_array}
        values = [(key, datewise_data.get(key, 0)) for key in date_range]

        time_series_data = append_data(values, interval=filter.interval, math=None)
        scaled_data, label = scale_time_series(time_series_data["data"])
        time_series_data.update({"data": scaled_data})
        # calculate average
        totals = [sum(x) for x in list(zip(*time_series_avg))[2:4]]
        overall_average = (totals[0] / totals[1]) if totals else 0
        avg_formatted = friendly_time(overall_average)
        avg_split = avg_formatted.split(" ")

        time_series_data.update(
            {
                "label": f"Average Session Length ({avg_split[1]})",
                "count": int(avg_split[0]),
                "aggregated_value": int(avg_split[0]),
            }
        )
        time_series_data.update({"chartLabel": f"Average Session Length ({label})"})
        result = [time_series_data]
        return result

    def _session_dist(self, base_query: Query, params: QueryParams) -> List[Dict[str, Any]]:
        distribution = "SELECT COUNT(CASE WHEN length = 0 THEN 1 ELSE NULL END) as first,\
                        COUNT(CASE WHEN length > 0 AND length <= 3 THEN 1 ELSE NULL END) as second,\
                        COUNT(CASE WHEN length > 3 AND length <= 10 THEN 1 ELSE NULL END) as third,\
                        COUNT(CASE WHEN length > 10 AND length <= 30 THEN 1 ELSE NULL END) as fourth,\
                        COUNT(CASE WHEN length > 30 AND length <= 60 THEN 1 ELSE NULL END) as fifth,\
                        COUNT(CASE WHEN length > 60 AND length <= 180 THEN 1 ELSE NULL END) as sixth,\
                        COUNT(CASE WHEN length > 180 AND length <= 600 THEN 1 ELSE NULL END) as seventh,\
                        COUNT(CASE WHEN length > 600 AND length <= 1800 THEN 1 ELSE NULL END) as eighth,\
                        COUNT(CASE WHEN length > 1800 AND length <= 3600 THEN 1 ELSE NULL END) as ninth,\
                        COUNT(CASE WHEN length > 3600 THEN 1 ELSE NULL END) as tenth\
                        FROM (SELECT global_session_id, EXTRACT('EPOCH' FROM (MAX(timestamp) - MIN(timestamp)))\
                            AS length FROM ({}) as count GROUP BY 1) agg".format(
            base_query
        )

        cursor = connection.cursor()
        cursor.execute(distribution, params)
        calculated = cursor.fetchall()
        result = [
            {"label": DIST_LABELS[index], "count": calculated[0][index], "aggregated_value": calculated[0][index]}
            for index in range(len(DIST_LABELS))
        ]
        return result


def scale_time_series(data: List[float]) -> Tuple[List, str]:
    _len = len([value for value in data if value > 0])
    if _len == 0:
        return data, "seconds"

    avg = sum(data) / _len
    minutes = avg // 60.0
    hours = minutes // 60.0

    if hours > 0:
        return [round(value / 3600, 2) for value in data], "hours"
    elif minutes > 0:
        return [round(value / 60, 2) for value in data], "minutes"
    else:
        return data, "seconds"
