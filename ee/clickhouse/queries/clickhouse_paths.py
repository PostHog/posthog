from typing import Dict, List, Optional

from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.events import EXTRACT_TAG_REGEX, EXTRACT_TEXT_REGEX
from ee.clickhouse.sql.paths.path import PATHS_QUERY_FINAL
from posthog.constants import AUTOCAPTURE_EVENT, CUSTOM_EVENT, SCREEN_EVENT
from posthog.models.filters import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.team import Team
from posthog.queries.paths import Paths
from posthog.utils import relative_date_parse


class ClickhousePaths(Paths):
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

    def calculate_paths(self, filter: PathFilter, team: Team):

        parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=filter, team_id=team.pk)
        event, path_type, start_comparator = self._determine_path_type(filter.path_type if filter else None)

        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team.pk)

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

        paths_query = PATHS_QUERY_FINAL.format(
            event_query="event = %(event)s"
            if event
            else "event NOT IN ('$autocapture', '$pageview', '$identify', '$pageleave', '$screen')",
            path_type=path_type,
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            filters=prop_filters,
            marked_session_start="{} = %(start_point)s".format(start_comparator)
            if filter and filter.start_point
            else "new_session",
            excess_row_filter=excess_row_filter,
            select_elements_chain=", events.elements_chain as elements_chain" if event == AUTOCAPTURE_EVENT else "",
            group_by_elements_chain=", events.elements_chain" if event == AUTOCAPTURE_EVENT else "",
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
