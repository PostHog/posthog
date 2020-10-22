from typing import Any, Dict, List, Tuple

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import ClickhouseEventSerializer
from ee.clickhouse.models.person import get_persons_by_distinct_ids
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import get_interval_annotation_ch, get_time_diff, parse_timestamps
from ee.clickhouse.sql.events import GET_EARLIEST_TIMESTAMP_SQL, NULL_SQL
from posthog.constants import SESSION_AVG, SESSION_DIST
from posthog.models import Filter, Person, Team
from posthog.queries.base import BaseQuery, determine_compared_filter
from posthog.utils import append_data, friendly_time

SESSIONS_LIST_DEFAULT_LIMIT = 50

SESSIONS_NO_EVENTS_SQL = """
SELECT
    distinct_id,
    uuid,
    event,
    properties,
    elements_chain,
    session_uuid,
    session_duration_seconds,
    timestamp,
    session_end_ts
FROM
(
    SELECT
        distinct_id,
        uuid,
        event,
        properties,
        elements_chain,
        if(is_new_session, uuid, NULL) AS session_uuid,
        is_new_session,
        is_end_session,
        if(is_end_session AND is_new_session, 0, if(is_new_session AND (NOT is_end_session), dateDiff('second', toDateTime(timestamp), toDateTime(neighbor(timestamp, 1))), NULL)) AS session_duration_seconds,
        timestamp,
        if(is_end_session AND is_new_session, timestamp, if(is_new_session AND (NOT is_end_session), neighbor(timestamp, 1), NULL)) AS session_end_ts
    FROM
    (
        SELECT
            distinct_id,
            uuid,
            event,
            properties,
            elements_chain,
            timestamp,
            neighbor(distinct_id, -1) AS start_possible_neighbor,
            neighbor(timestamp, -1) AS start_possible_prev_ts,
            if((start_possible_neighbor != distinct_id) OR (dateDiff('minute', toDateTime(start_possible_prev_ts), toDateTime(timestamp)) > 30), 1, 0) AS is_new_session,
            neighbor(distinct_id, 1) AS end_possible_neighbor,
            neighbor(timestamp, 1) AS end_possible_prev_ts,
            if((end_possible_neighbor != distinct_id) OR (dateDiff('minute', toDateTime(timestamp), toDateTime(end_possible_prev_ts)) > 30), 1, 0) AS is_end_session
        FROM
        (
            SELECT
                uuid,
                event,
                properties,
                timestamp,
                distinct_id,
                elements_chain
            FROM events
            WHERE 
                team_id = %(team_id)s
                {date_from}
                {date_to} 
                {filters}
            GROUP BY
                uuid,
                event,
                properties,
                timestamp,
                distinct_id,
                elements_chain
            ORDER BY
                distinct_id ASC,
                timestamp ASC
        )
    )
    WHERE (is_new_session AND (NOT is_end_session)) OR (is_end_session AND (NOT is_new_session)) OR (is_end_session AND is_new_session)
)
WHERE is_new_session
{sessions_limit}
"""

SESSION_SQL = """
    SELECT 
        distinct_id, 
        gid, 
        dateDiff('second', toDateTime(arrayReduce('min', groupArray(timestamp))), toDateTime(arrayReduce('max', groupArray(timestamp)))) AS elapsed,
        arrayReduce('min', groupArray(timestamp)) as start_time,
        groupArray(uuid) uuids, 
        groupArray(event) events, 
        groupArray(properties) properties, 
        groupArray(timestamp) timestamps, 
        groupArray(elements_chain) elements_chain
    FROM (
        SELECT
            distinct_id, 
            event,
            timestamp,
            uuid,
            properties,
            elements_chain,
            arraySum(arraySlice(gids, 1, idx)) AS gid
        FROM (
            SELECT 
                groupArray(timestamp) as timestamps, 
                groupArray(event) as events, 
                groupArray(uuid) as uuids, 
                groupArray(properties) as property_list, 
                groupArray(elements_chain) as elements_chains, 
                groupArray(distinct_id) as distinct_ids, 
                groupArray(new_session) AS gids
            FROM (
                SELECT 
                    distinct_id,
                    uuid,
                    event,
                    properties,
                    elements_chain,
                    timestamp, 
                    neighbor(distinct_id, -1) as possible_neighbor,
                    neighbor(timestamp, -1) as possible_prev, 
                    if(possible_neighbor != distinct_id or dateDiff('minute', toDateTime(possible_prev), toDateTime(timestamp)) > 30, 1, 0) as new_session
                FROM (
                    SELECT 
                        uuid,
                        event,
                        properties,
                        timestamp, 
                        distinct_id,
                        elements_chain
                    FROM    
                        events 
                    WHERE 
                        team_id = %(team_id)s
                        {date_from}
                        {date_to} 
                        {filters}
                    GROUP BY 
                        uuid,
                        event,
                        properties,
                        timestamp, 
                        distinct_id,
                        elements_chain 
                    ORDER BY 
                        distinct_id, 
                        timestamp
                )
            )
        )
        ARRAY JOIN
            distinct_ids as distinct_id,
            events as event,
            timestamps as timestamp,
            uuids as uuid,
            property_list as properties,
            elements_chains as elements_chain,
            arrayEnumerate(gids) AS idx 
    ) 
    GROUP BY 
        distinct_id, 
        gid
    {sessions_limit}
"""

AVERAGE_PER_PERIOD_SQL = """
    SELECT 
        AVG(session_duration_seconds) as total, 
        {interval}(timestamp) as day_start 
    FROM 
        ({sessions}) 
    GROUP BY 
        {interval}(timestamp)
"""

AVERAGE_SQL = """
    SELECT 
        SUM(total), 
        day_start 
    FROM 
        ({null_sql} UNION ALL {sessions}) 
    GROUP BY 
        day_start 
    ORDER BY 
        day_start
"""

DIST_SQL = """
    SELECT 
        countIf(session_duration_seconds = 0)  as first,
        countIf(session_duration_seconds > 0 and session_duration_seconds <= 3)  as second,
        countIf(session_duration_seconds > 3 and session_duration_seconds <= 10)  as third,
        countIf(session_duration_seconds > 10 and session_duration_seconds <= 30)  as fourth,
        countIf(session_duration_seconds > 30 and session_duration_seconds <= 60)  as fifth,
        countIf(session_duration_seconds > 60 and session_duration_seconds <= 180)  as sixth,
        countIf(session_duration_seconds > 180 and session_duration_seconds <= 600)  as sevent,
        countIf(session_duration_seconds > 600 and session_duration_seconds <= 1800)  as eighth,
        countIf(session_duration_seconds > 1800 and session_duration_seconds <= 3600)  as ninth,
        countIf(session_duration_seconds > 3600)  as tenth
    FROM 
        ({sessions})
""".format(
    sessions=SESSIONS_NO_EVENTS_SQL
)

# TODO: handle date and defaults
class ClickhouseSessions(BaseQuery):
    def calculate_list(self, filter: Filter, team: Team, limit: int, offset: int):
        filters, params = parse_prop_clauses("uuid", filter.properties, team)

        if not filter._date_from:
            filter._date_from = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if not filter._date_to and filter.date_from:
            filter._date_to = filter.date_from + relativedelta(days=1)

        date_from, date_to = parse_timestamps(filter)
        params = {**params, "team_id": team.pk, "limit": limit, "offset": offset}
        query = SESSION_SQL.format(
            date_from=date_from,
            date_to=date_to,
            filters="{}".format(filters) if filter.properties else "",
            sessions_limit="LIMIT %(offset)s, %(limit)s",
        )
        query_result = sync_execute(query, params)
        result = self._parse_list_results(query_result)

        self._add_person_properties(team, result)

        return result

    def _parse_list_results(self, results: List[Tuple]):
        final = []
        for result in results:
            events = []
            for i in range(len(result[4])):
                event = [
                    result[4][i],  # uuid
                    result[5][i],  # event
                    result[6][i],  # properties
                    result[7][i],  # timestamp
                    None,  # team_id,
                    result[0],  # distinct_id
                    result[8][i],  # elements_chain
                    None,  # properties keys
                    None,  # properties values
                ]
                events.append(ClickhouseEventSerializer(event, many=False).data)

            final.append(
                {
                    "distinct_id": result[0],
                    "global_session_id": result[1],
                    "length": result[2],
                    "start_time": result[3],
                    "event_count": len(result[4]),
                    "events": list(events),
                    "properties": {},
                }
            )

        return final

    def _add_person_properties(self, team=Team, sessions=List[Tuple]):
        distinct_id_hash = {}
        for session in sessions:
            distinct_id_hash[session["distinct_id"]] = True
        distinct_ids = list(distinct_id_hash.keys())

        if len(distinct_ids) == 0:
            return

        persons = get_persons_by_distinct_ids(team.pk, distinct_ids)

        distinct_to_person: Dict[str, Person] = {}
        for person in persons:
            for distinct_id in person.distinct_ids:
                distinct_to_person[distinct_id] = person

        for session in sessions:
            if distinct_to_person.get(session["distinct_id"], None):
                session["properties"] = distinct_to_person[session["distinct_id"]].properties

    def calculate_avg(self, filter: Filter, team: Team):
        parsed_date_from, parsed_date_to = parse_timestamps(filter)

        filters, params = parse_prop_clauses("uuid", filter.properties, team)

        interval_notation = get_interval_annotation_ch(filter.interval)
        num_intervals, seconds_in_interval = get_time_diff(filter.interval or "day", filter.date_from, filter.date_to)

        avg_query = SESSIONS_NO_EVENTS_SQL.format(
            team_id=team.pk,
            date_from=parsed_date_from,
            date_to=parsed_date_to,
            filters="{}".format(filters) if filter.properties else "",
            sessions_limit="",
        )
        per_period_query = AVERAGE_PER_PERIOD_SQL.format(sessions=avg_query, interval=interval_notation)

        null_sql = NULL_SQL.format(
            date_to=(filter.date_to or timezone.now()).strftime("%Y-%m-%d 00:00:00"),
            interval=interval_notation,
            num_intervals=num_intervals,
            seconds_in_interval=seconds_in_interval,
        )

        final_query = AVERAGE_SQL.format(sessions=per_period_query, null_sql=null_sql)

        params = {**params, "team_id": team.pk}
        response = sync_execute(final_query, params)
        values = self.clean_values(filter, response)
        time_series_data = append_data(values, interval=filter.interval, math=None)
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
            {"label": "Average Duration of Session ({})".format(avg_split[1]), "count": int(avg_split[0]),}
        )
        time_series_data.update({"chartLabel": "Average Duration of Session (seconds)"})
        return time_series_data

    def calculate_dist(self, filter: Filter, team: Team):

        parsed_date_from, parsed_date_to = parse_timestamps(filter)

        filters, params = parse_prop_clauses("uuid", filter.properties, team)
        dist_query = DIST_SQL.format(
            team_id=team.pk,
            date_from=parsed_date_from,
            date_to=parsed_date_to,
            filters="{}".format(filters) if filter.properties else "",
            sessions_limit="",
        )

        params = {**params, "team_id": team.pk}

        result = sync_execute(dist_query, params)

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

        res = [{"label": dist_labels[index], "count": result[0][index]} for index in range(len(dist_labels))]

        return res

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        limit = kwargs.get("limit", SESSIONS_LIST_DEFAULT_LIMIT)
        offset = kwargs.get("offset", 0)

        result: List = []
        if filter.session_type == SESSION_AVG:

            if filter.compare:
                current_response = self.calculate_avg(filter, team)
                parsed_response = convert_to_comparison(current_response, "current", filter)
                result.extend(parsed_response)

                compared_filter = determine_compared_filter(filter)
                compared_result = self.calculate_avg(compared_filter, team)
                compared_res = convert_to_comparison(compared_result, "previous", filter)
                result.extend(compared_res)
            else:
                result = self.calculate_avg(filter, team)

        elif filter.session_type == SESSION_DIST:
            result = self.calculate_dist(filter, team)
        else:
            result = self.calculate_list(filter, team, limit, offset)

        return result


def convert_to_comparison(trend_entity: List[Dict[str, Any]], label: str, filter: Filter) -> List[Dict[str, Any]]:
    for entity in trend_entity:
        days = [i for i in range(len(entity["days"]))]
        labels = ["{} {}".format(filter.interval or "Day", i) for i in range(len(entity["labels"]))]
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
