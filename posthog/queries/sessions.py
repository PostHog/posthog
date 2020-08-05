import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from dateutil.relativedelta import relativedelta
from django.db import connection
from django.db.models import F, Q, QuerySet
from django.db.models.expressions import Window
from django.db.models.functions import Lag
from django.utils.timezone import now

from posthog.api.element import ElementSerializer
from posthog.models import ElementGroup, Event, Filter, Team
from posthog.queries.base import BaseQuery, determine_compared_filter
from posthog.utils import append_data, dict_from_cursor_fetchall, friendly_time


class Sessions(BaseQuery):
    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        events = (
            Event.objects.filter(team=team)
            .filter(filter.properties_to_Q(team_id=team.pk))
            .add_person_id(team.pk)
            .order_by("-timestamp")
        )

        session_type = kwargs.get("session_type", None)
        offset = kwargs.get("offset", 0)

        if not filter.date_to:
            filter._date_to = now().isoformat()
        calculated = []

        # get compared period
        if filter.compare and filter._date_from != "all" and session_type == "avg":
            calculated = self.calculate_sessions(
                events.filter(filter.date_filter_Q), session_type, filter, team, offset
            )
            calculated = self._convert_to_comparison(calculated, "current")

            compare_filter = determine_compared_filter(filter)
            compared_calculated = self.calculate_sessions(
                events.filter(compare_filter.date_filter_Q), session_type, compare_filter, team, offset
            )
            converted_compared_calculated = self._convert_to_comparison(compared_calculated, "previous")
            calculated.extend(converted_compared_calculated)
        else:
            # if session_type is None, it's a list of sessions which shouldn't have any date filtering
            if session_type is not None:
                events = events.filter(filter.date_filter_Q)
            calculated = self.calculate_sessions(events, session_type, filter, team, offset)

        return calculated

    def calculate_sessions(
        self, events: QuerySet, session_type: Optional[str], filter: Filter, team: Team, offset: int
    ) -> List[Dict[str, Any]]:

        # format date filter for session view
        _date_gte = Q()
        if session_type is None:
            # if _date_from is not explicitely set we only want to get the last day worth of data
            # otherwise the query is very slow
            if filter._date_from and filter.date_to:
                _date_gte = Q(timestamp__gte=filter.date_from, timestamp__lte=filter.date_to + relativedelta(days=1),)
            else:
                dt = now()
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                _date_gte = Q(timestamp__gte=dt, timestamp__lte=dt + relativedelta(days=1))
        else:
            if not filter.date_from:
                filter._date_from = (
                    Event.objects.filter(team_id=team)
                    .order_by("timestamp")[0]
                    .timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
                    .isoformat()
                )

        sessions = (
            events.filter(_date_gte)
            .annotate(
                previous_timestamp=Window(
                    expression=Lag("timestamp", default=None),
                    partition_by=F("distinct_id"),
                    order_by=F("timestamp").asc(),
                )
            )
            .annotate(
                previous_event=Window(
                    expression=Lag("event", default=None), partition_by=F("distinct_id"), order_by=F("timestamp").asc(),
                )
            )
        )

        sessions_sql, sessions_sql_params = sessions.query.sql_with_params()
        all_sessions = "\
            SELECT *,\
                SUM(new_session) OVER (ORDER BY distinct_id, timestamp) AS global_session_id,\
                SUM(new_session) OVER (PARTITION BY distinct_id ORDER BY timestamp) AS user_session_id\
                FROM (SELECT id, distinct_id, event, elements_hash, timestamp, properties, CASE WHEN EXTRACT('EPOCH' FROM (timestamp - previous_timestamp)) >= (60 * 30)\
                    OR previous_timestamp IS NULL \
                    THEN 1 ELSE 0 END AS new_session \
                    FROM ({}) AS inner_sessions\
                ) AS outer_sessions".format(
            sessions_sql
        )

        result: List = []
        if session_type == "avg":
            result = self._session_avg(all_sessions, sessions_sql_params, filter)
        elif session_type == "dist":
            result = self._session_dist(all_sessions, sessions_sql_params)
        else:
            result = self._session_list(all_sessions, sessions_sql_params, team, filter, offset)

        return result

    def _session_list(
        self, base_query: str, params: Tuple[Any, ...], team: Team, filter: Filter, offset: int
    ) -> List[Dict[str, Any]]:
        session_list = "SELECT * FROM (SELECT global_session_id, properties, start_time, length, sessions.distinct_id, event_count, events from\
                                (SELECT\
                                    global_session_id,\
                                    count(1) as event_count,\
                                    MAX(distinct_id) as distinct_id,\
                                    EXTRACT('EPOCH' FROM (MAX(timestamp) - MIN(timestamp))) AS length,\
                                    MIN(timestamp) as start_time,\
                                    array_agg(json_build_object( 'id', id, 'event', event, 'timestamp', timestamp, 'properties', properties, 'elements_hash', elements_hash) ORDER BY timestamp) as events\
                                        FROM ({}) as count GROUP BY 1) as sessions\
                                        LEFT OUTER JOIN posthog_persondistinctid ON posthog_persondistinctid.distinct_id = sessions.distinct_id\
                                        LEFT OUTER JOIN posthog_person ON posthog_person.id = posthog_persondistinctid.person_id\
                                        ORDER BY start_time DESC) as ordered_sessions OFFSET %s LIMIT 50".format(
            base_query
        )

        with connection.cursor() as cursor:
            params = params + (offset,)
            cursor.execute(session_list, params)
            sessions = dict_from_cursor_fetchall(cursor)

            hash_ids = []
            for session in sessions:
                for event in session["events"]:
                    if event.get("elements_hash"):
                        hash_ids.append(event["elements_hash"])

            groups = self._prefetch_elements(hash_ids, team)

            for session in sessions:
                for event in session["events"]:
                    try:
                        event.update(
                            {
                                "elements": ElementSerializer(
                                    [group for group in groups if group.hash == event["elements_hash"]][0]
                                    .element_set.all()
                                    .order_by("order"),
                                    many=True,
                                ).data
                            }
                        )
                    except IndexError:
                        event.update({"elements": []})
        return sessions

    def _session_avg(self, base_query: str, params: Tuple[Any, ...], filter: Filter) -> List[Dict[str, Any]]:
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

        date_range = pd.date_range(filter.date_from, filter.date_to, freq=interval_freq,)
        df = pd.DataFrame([{"date": a[0], "count": a[1], "breakdown": "Total"} for a in time_series_avg])
        if interval == "week":
            df["date"] = df["date"].apply(lambda x: x - pd.offsets.Week(weekday=6))
        elif interval == "month":
            df["date"] = df["date"].apply(lambda x: x - pd.offsets.MonthEnd(n=0))

        df_dates = pd.DataFrame(df.groupby("date").mean(), index=date_range)
        df_dates = df_dates.fillna(0)
        values = [(key, round(value[0])) if len(value) > 0 else (key, 0) for key, value in df_dates.iterrows()]

        time_series_data = append_data(values, interval=filter.interval, math=None)
        # calculate average
        totals = [sum(x) for x in list(zip(*time_series_avg))[2:4]]
        overall_average = (totals[0] / totals[1]) if totals else 0
        avg_formatted = friendly_time(overall_average)
        avg_split = avg_formatted.split(" ")

        time_series_data.update(
            {"label": "Average Duration of Session ({})".format(avg_split[1]), "count": int(avg_split[0]),}
        )
        time_series_data.update({"chartLabel": "Average Duration of Session (seconds)"})
        result = [time_series_data]
        return result

    def _session_dist(self, base_query: str, params: Tuple[Any, ...]) -> List[Dict[str, Any]]:
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

        dist_labels = [
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
        cursor = connection.cursor()
        cursor.execute(distribution, params)
        calculated = cursor.fetchall()
        result = [{"label": dist_labels[index], "count": calculated[0][index]} for index in range(len(dist_labels))]
        return result

    def _convert_to_comparison(self, trend_entity: List[Dict[str, Any]], label: str) -> List[Dict[str, Any]]:
        for entity in trend_entity:
            days = [i for i in range(len(entity["days"]))]
            labels = ["{} {}".format("Day", i) for i in range(len(entity["labels"]))]
            entity.update(
                {
                    "labels": labels,
                    "days": days,
                    "chartLabel": "{} - {}".format(entity["label"], label),
                    "dates": entity["days"],
                    "compare": True,
                }
            )
        return trend_entity

    def _prefetch_elements(self, hash_ids: List[str], team: Team) -> QuerySet:
        groups = ElementGroup.objects.none()
        if len(hash_ids) > 0:
            groups = ElementGroup.objects.filter(team=team, hash__in=hash_ids).prefetch_related("element_set")
        return groups
