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
                path_type = "tag_name_source"
                start_comparator = "group_id"
            elif requested_type == CUSTOM_EVENT:
                event = None
                path_type = "event"
        return event, path_type, start_comparator

    # def _add_elements(self, query_string: str) -> str:
    #     element = 'SELECT \'<\'|| e."tag_name" || \'> \'  || e."text" as tag_name_source, e."text" as text_source FROM "posthog_element" e JOIN \
    #                 ( SELECT group_id, MIN("posthog_element"."order") as minOrder FROM "posthog_element" GROUP BY group_id) e2 ON e.order = e2.minOrder AND e.group_id = e2.group_id where e.group_id = v2.group_id'
    #     element_group = 'SELECT g."id" as group_id FROM "posthog_elementgroup" g where v1."elements_hash" = g."hash"'
    #     sessions_sql = "SELECT * FROM ({}) as v1 JOIN LATERAL ({}) as v2 on true JOIN LATERAL ({}) as v3 on true".format(
    #         query_string, element_group, element
    #     )
    #     return sessions_sql

    def calculate_paths(self, filter: Filter, team: Team):
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)
        event, path_type, start_comparator = self._determine_path_type(filter.path_type if filter else None)

        prop_filters, prop_filter_params = parse_prop_clauses("id", filter.properties, team)

        sessions_query = """
            SELECT distinct_id,
                   event_id,
                   timestamp,
                   path_type,
                   IF(
                      neighbor(distinct_id, -1) != distinct_id
                        OR dateDiff('minute', toDateTime(neighbor(timestamp, -1)), toDateTime(timestamp)) > 30, 
                      1,
                      0
                   ) AS new_session,
                   (new_session = 1 AND {marked_session}) as marked_session
            FROM (
                    SELECT timestamp,
                           distinct_id,
                           id AS event_id,
                           {path_type} AS path_type
                    FROM events
                    WHERE team_id = %(team_id)s 
                          AND {event_query}
                          {filters}
                          {parsed_date_from}
                          {parsed_date_to}
                    GROUP BY distinct_id, timestamp, event_id, properties {extra_group_by}
                    ORDER BY distinct_id, timestamp
            )
        """.format(
            event_query="event = %(event)s"
            if event
            else "event NOT IN ('$autocapture', '$pageview', '$identify', '$pageleave', '$screen')",
            path_type=path_type,
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            extra_group_by=", {}".format(path_type) if path_type == "event" or path_type == "tag_name_source" else "",
            filters=prop_filters if filter.properties else "",
            marked_session="{} = %(start_point)s".format(start_comparator) if filter and filter.start_point else "1",
        )

        # if event == "$autocapture":
        #     sessions_sql = self._add_elements(query_string=sessions_sql)

        aggregate_query = """
            SELECT concat(toString(group_index), '_', path_type)                                          AS target_event,
                   event_id                                                                               AS target_event_id,
                   if(group_index > 1, neighbor(concat(toString(group_index), '_', path_type), -1), null) AS source_event,
                   if(group_index > 1, neighbor(event_id, -1), null)                                      AS source_event_id
            FROM (
                  SELECT distinct_id,
                         event_id,
                         timestamp,
                         path_type,
                         indexOf(arrayReverse(arraySlice(gids, 1, idx)), 1) AS group_index,
                         marked_session,
                         neighbor(marked_session, -group_index + 1) as marked_group
                  FROM (
                        SELECT groupArray(timestamp)      AS timestamps,
                               groupArray(path_type)      AS path_types,
                               groupArray(event_id)       AS event_ids,
                               groupArray(distinct_id)    AS distinct_ids,
                               groupArray(new_session)    AS gids,
                               groupArray(marked_session) AS marked_sessions
                         FROM ({sessions_query})
                       )
                  ARRAY JOIN
                       distinct_ids AS distinct_id,
                       event_ids AS event_id,
                       timestamps AS timestamp,
                       path_types AS path_type,
                       marked_sessions AS marked_session,
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

        final_query = count_query.format(aggregate_query=aggregate_query.format(sessions_query=sessions_query))

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
