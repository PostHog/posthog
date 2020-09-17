from typing import Any, Dict, List, Optional

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from posthog.constants import AUTOCAPTURE_EVENT, CUSTOM_EVENT, SCREEN_EVENT
from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.base import BaseQuery


class ClickhousePaths(BaseQuery):
    def _determine_path_type(self, requested_type=None):
        # Default
        event: Optional[str] = "$pageview"
        path_type = "JSONExtractString(properties, '$current_url')"
        start_comparator = "path_type"

        # determine requested type
        if requested_type:
            if requested_type == SCREEN_EVENT:
                event = SCREEN_EVENT
                path_type = "JSONExtractString(properties, '$screen_name')"
            elif requested_type == AUTOCAPTURE_EVENT:
                event = AUTOCAPTURE_EVENT
                path_type = "concat('<', elements.tag_name, '> ', elements.text)"
                start_comparator = "group_id"
            elif requested_type == CUSTOM_EVENT:
                event = None
                path_type = "event"
        return event, path_type, start_comparator

    def calculate_paths(self, filter: Filter, team: Team):
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)
        event, path_type, start_comparator = self._determine_path_type(filter.path_type if filter else None)

        prop_filters, prop_filter_params = parse_prop_clauses("id", filter.properties, team)

        # new_session = this is 1 when the event is from a new session or
        #                       0 if it's less than 30min after and for the same person_id as the previous event
        # marked_session_start = this is the same as "new_session" if no start point given, otherwise it's 1 if
        #                        the current event is the start point (e.g. path_start=/about) or 0 otherwise
        sessions_query = """
            SELECT person_id,
                   event_id,
                   timestamp,
                   path_type,
                   IF(
                      neighbor(person_id, -1) != person_id
                        OR dateDiff('minute', toDateTime(neighbor(timestamp, -1)), toDateTime(timestamp)) > 30, 
                      1,
                      0
                   ) AS new_session,
                   {marked_session_start} as marked_session_start
            FROM (
                    SELECT timestamp,
                           person_id,
                           events.id AS event_id,
                           {path_type} AS path_type
                    FROM events
                    JOIN person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
                    {element_joins}
                    WHERE events.team_id = %(team_id)s 
                          AND {event_query}
                          {filters}
                          {parsed_date_from}
                          {parsed_date_to}
                    GROUP BY person_id, timestamp, event_id, path_type
                    ORDER BY person_id, timestamp
            )
        """.format(
            event_query="event = %(event)s"
            if event
            else "event NOT IN ('$autocapture', '$pageview', '$identify', '$pageleave', '$screen')",
            path_type=path_type,
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            filters=prop_filters if filter.properties else "",
            marked_session_start="{} = %(start_point)s".format(start_comparator)
            if filter and filter.start_point
            else "new_session",
            element_joins="JOIN elements_group ON elements_group.elements_hash = events.elements_hash\
            JOIN elements ON (elements.group_id = elements_group.id AND elements.order = toInt32(0))"
            if event == AUTOCAPTURE_EVENT
            else "",
        )

        if filter and filter.start_point:
            # find the first "marked_session_start" in the group and restart counting from it
            marked_group_index_variable = """
                indexOf(arraySlice(marked_session_starts, idx - group_index + 1, group_index), 1) as index_from_marked,
                index_from_marked > 0 ? toUInt64(group_index - index_from_marked + 1) : group_index as marked_group_index
            """
        else:
            # otherwise just use the group index
            marked_group_index_variable = "group_index as marked_group_index"

        aggregate_query = """
            SELECT concat(toString(marked_group_index), '_', path_type)                                                 AS target_event,
                   event_id                                                                                             AS target_event_id,
                   if(marked_group_index > 1, neighbor(concat(toString(marked_group_index), '_', path_type), -1), null) AS source_event,
                   if(marked_group_index > 1, neighbor(event_id, -1), null)                                             AS source_event_id
            FROM (
                  SELECT person_id,
                         event_id,
                         timestamp,
                         path_type,
                         indexOf(arrayReverse(arraySlice(gids, 1, idx)), 1) AS group_index,
                         {marked_group_index_variable},
                         neighbor(marked_session_start, -marked_group_index + 1) as marked_group
                  FROM (
                        SELECT groupArray(timestamp)            AS timestamps,
                               groupArray(path_type)            AS path_types,
                               groupArray(event_id)             AS event_ids,
                               groupArray(person_id)          AS person_ids,
                               groupArray(new_session)          AS gids,
                               groupArray(marked_session_start) AS marked_session_starts
                         FROM ({sessions_query})
                       )
                  ARRAY JOIN
                       person_ids AS person_id,
                       event_ids AS event_id,
                       timestamps AS timestamp,
                       path_types AS path_type,
                       marked_session_starts AS marked_session_start,
                       arrayEnumerate(gids) AS idx
            )
            WHERE group_index <= %(query_depth)s AND marked_group = 1
        """

        count_query = """
            SELECT 
                source_event         AS source_event, 
                any(source_event_id) AS source_event_id, 
                target_event         AS target_event, 
                any(target_event_id) AS target_event_id, 
                COUNT(*)             AS event_count
            FROM ({aggregate_query}) 
            WHERE source_event IS NOT NULL 
              AND target_event IS NOT NULL
            GROUP BY source_event, target_event
            ORDER BY event_count DESC, source_event, target_event
        """

        final_query = count_query.format(
            aggregate_query=aggregate_query.format(
                sessions_query=sessions_query, marked_group_index_variable=marked_group_index_variable
            )
        )

        params: Dict = {
            "team_id": team.pk,
            "property": "$current_url",
            "event": event,
            "query_depth": 4,
            "start_point": filter.start_point,
        }
        params = {**params, **prop_filter_params}

        rows = sync_execute(final_query, params)

        resp: List[Dict[str, str]] = []
        for row in rows:
            resp.append(
                {"source": row[0], "target": row[2], "target_id": row[3], "source_id": row[1], "value": row[4],}
            )

        resp = sorted(resp, key=lambda x: x["value"], reverse=True)
        return resp

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return self.calculate_paths(filter=filter, team=team)
