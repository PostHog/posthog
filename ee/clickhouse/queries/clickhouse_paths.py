from typing import Any, Dict, List, Optional

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.events import EXTRACT_TAG_REGEX, EXTRACT_TEXT_REGEX
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
                path_type = "concat('<', {tag_regex}, '> ', {text_regex})".format(
                    tag_regex=EXTRACT_TAG_REGEX, text_regex=EXTRACT_TEXT_REGEX
                )
                start_comparator = "elements_chain"
            elif requested_type == CUSTOM_EVENT:
                event = None
                path_type = "event"
        return event, path_type, start_comparator

    def calculate_paths(self, filter: Filter, team: Team):
        parsed_date_from, parsed_date_to = parse_timestamps(filter=filter)
        event, path_type, start_comparator = self._determine_path_type(filter.path_type if filter else None)

        prop_filters, prop_filter_params = parse_prop_clauses("uuid", filter.properties, team)

        # Step 0. Event culling subexpression for step 1.
        # Make an expression that removes events in a session that are definitely unused.
        # For example the 4th, 5th, etc row after a "new_session = 1" or "marked_session_start = 1" row gets removed
        excess_row_filter = "("
        for i in range(4):
            if i > 0:
                excess_row_filter += " or "
            excess_row_filter += "neighbor(new_session, {}, 0) = 1".format(-i)
            if filter and filter.start_point:
                excess_row_filter += " or neighbor(marked_session_start, {}, 0) = 1".format(-i)
        excess_row_filter += ")"

        # Step 1. Make a table with the following fields from events:
        #
        # - person_id = dedupe event distinct_ids into person_id
        # - timestamp
        # - path_type = either name of event or $current_url or ...
        # - new_session = this is 1 when the event is from a new session
        #                 or 0 if it's less than 30min after and for the same person_id as the previous event
        # - marked_session_start = this is the same as "new_session" if no start point given, otherwise it's 1 if
        #                          the current event is the start point (e.g. path_start=/about) or 0 otherwise
        paths_query = """
            SELECT 
                person_id,
                timestamp,
                event_id,
                path_type,
                neighbor(person_id, -1) != person_id OR dateDiff('minute', toDateTime(neighbor(timestamp, -1)), toDateTime(timestamp)) > 30 AS new_session,
                {marked_session_start} as marked_session_start
            FROM (
                SELECT 
                    timestamp,
                    person_id,
                    events.uuid AS event_id,
                    {path_type} AS path_type
                    {select_elements_chain}
                FROM events_with_array_props_view AS events
                JOIN person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
                WHERE 
                    events.team_id = %(team_id)s 
                    AND {event_query}
                    {filters}
                    {parsed_date_from}
                    {parsed_date_to}
                GROUP BY 
                    person_id, 
                    timestamp, 
                    event_id, 
                    path_type
                    {group_by_elements_chain}
                ORDER BY 
                    person_id, 
                    timestamp
            )
            WHERE {excess_row_filter}
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
            excess_row_filter=excess_row_filter,
            select_elements_chain=", events.elements_chain as elements_chain" if event == AUTOCAPTURE_EVENT else "",
            group_by_elements_chain=", events.elements_chain" if event == AUTOCAPTURE_EVENT else "",
        )

        # Step 2.
        # - Convert new_session = {1 or 0} into
        #      ---> session_id = {1, 2, 3...}
        # - Remove all "marked_session_start = 0" rows at the start of a session
        paths_query = """
            SELECT 
                person_id,
                event_id,
                timestamp,
                path_type,
                runningAccumulate(session_id_sumstate) as session_id
            FROM (
                SELECT 
                    *,
                    sumState(new_session) AS session_id_sumstate
                FROM 
                    ({paths_query})
                GROUP BY
                    person_id,
                    timestamp,
                    event_id,
                    path_type,
                    new_session,
                    marked_session_start
                ORDER BY 
                    person_id, 
                    timestamp
            )
            WHERE
                marked_session_start = 1 or
                (neighbor(marked_session_start, -1) = 1 and neighbor(session_id, -1) = session_id) or
                (neighbor(marked_session_start, -2) = 1 and neighbor(session_id, -2) = session_id) or
                (neighbor(marked_session_start, -3) = 1 and neighbor(session_id, -3) = session_id)
        """.format(
            paths_query=paths_query
        )

        # Step 3.
        # - Add event index per session
        # - Use the index and path_type to create a path key (e.g. "1_/pricing", "2_/help")
        # - Remove every unused row per session (5th and later rows)
        #   Those rows will only be there if many filter.start_point rows are in a query.
        #   For example start_point=/pricing and the user clicked back and forth between pricing and other pages.
        paths_query = """
            SELECT
                person_id,
                event_id,
                timestamp,
                path_type,
                session_id,
                (neighbor(session_id, -4) = session_id ? 5 :
                (neighbor(session_id, -3) = session_id ? 4 :
                (neighbor(session_id, -2) = session_id ? 3 :
                (neighbor(session_id, -1) = session_id ? 2 : 1)))) as session_index,
                concat(toString(session_index), '_', path_type) as path_key,
                if(session_index > 1, neighbor(path_key, -1), null) AS last_path_key,
                if(session_index > 1, neighbor(event_id, -1), null) AS last_event_id
            FROM ({paths_query})
            WHERE
                session_index <= 4
        """.format(
            paths_query=paths_query
        )

        # Step 4.
        # - Aggregate and get counts for unique pairs
        # - Filter out the entry rows that come from "null"
        paths_query = """
            SELECT 
                last_path_key as source_event,
                any(last_event_id) as source_event_id,
                path_key as target_event,
                any(event_id) target_event_id, 
                COUNT(*) AS event_count
            FROM (
                {paths_query}
            )
            WHERE 
                source_event IS NOT NULL
                AND target_event IS NOT NULL
            GROUP BY
                source_event,
                target_event
            ORDER BY
                event_count DESC,
                source_event,
                target_event
            LIMIT 20
        """.format(
            paths_query=paths_query
        )

        params: Dict = {
            "team_id": team.pk,
            "property": "$current_url",
            "event": event,
            "start_point": filter.start_point,
        }
        params = {**params, **prop_filter_params}

        rows = sync_execute(paths_query, params)

        resp: List[Dict[str, str]] = []
        for row in rows:
            resp.append(
                {"source": row[0], "source_id": row[1], "target": row[2], "target_id": row[3], "value": row[4],}
            )

        resp = sorted(resp, key=lambda x: x["value"], reverse=True)
        return resp

    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return self.calculate_paths(filter=filter, team=team)
