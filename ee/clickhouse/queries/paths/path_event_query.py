from typing import Any, Dict, Tuple

from ee.clickhouse.models.property import get_property_string_expr
from ee.clickhouse.queries.event_query import ClickhouseEventQuery
from posthog.constants import AUTOCAPTURE_EVENT, PAGEVIEW_EVENT, SCREEN_EVENT
from posthog.models.filters.path_filter import PathFilter


class PathEventQuery(ClickhouseEventQuery):
    FUNNEL_PERSONS_ALIAS = "funnel_persons"

    def get_query(self) -> Tuple[str, Dict[str, Any]]:

        funnel_paths_timestamp = ""
        funnel_paths_join = ""
        funnel_paths_filter = ""

        if self._filter.funnel_paths:
            funnel_paths_timestamp = f", {self.FUNNEL_PERSONS_ALIAS}.timestamp as min_timestamp"
            funnel_paths_join = f"JOIN {self.FUNNEL_PERSONS_ALIAS} ON {self.FUNNEL_PERSONS_ALIAS}.person_id = {self.DISTINCT_ID_TABLE_ALIAS}.person_id"
            funnel_paths_filter = f"AND {self.EVENT_TABLE_ALIAS}.timestamp >= min_timestamp"

        _fields = (
            f"{self.EVENT_TABLE_ALIAS}.timestamp AS timestamp, if(event = %(screen)s, {self._get_screen_name_parsing()}, if({self.EVENT_TABLE_ALIAS}.event = %(pageview)s, {self._get_current_url_parsing()}, if({self.EVENT_TABLE_ALIAS}.event = %(autocapture)s, concat('autocapture:', {self.EVENT_TABLE_ALIAS}.elements_chain), {self.EVENT_TABLE_ALIAS}.event))) AS path_item"
            + (f", {self.DISTINCT_ID_TABLE_ALIAS}.person_id as person_id" if self._should_join_distinct_ids else "")
            + funnel_paths_timestamp
        )

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_filters = self._filter.properties
        prop_query, prop_params = self._get_props(prop_filters)
        self.params.update(prop_params)

        query = f"""
            SELECT {_fields} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_disintct_id_query()}
            {self._get_person_query()}
            {funnel_paths_join}
            WHERE team_id = %(team_id)s
            AND (event = %(pageview)s OR event = %(screen)s OR event = %(autocapture)s OR NOT event LIKE %(custom_event_match)s)
            {date_query}
            {prop_query}
            {funnel_paths_filter}
            ORDER BY {self.DISTINCT_ID_TABLE_ALIAS}.person_id, {self.EVENT_TABLE_ALIAS}.timestamp
        """
        self.params.update(
            {
                "custom_event_match": "$%",
                "pageview": PAGEVIEW_EVENT,
                "screen": SCREEN_EVENT,
                "autocapture": AUTOCAPTURE_EVENT,
            }
        )
        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
        self._should_join_distinct_ids = True

    def _get_current_url_parsing(self):
        path_type, _ = get_property_string_expr("events", "$current_url", "'$current_url'", "properties")
        return path_type

    def _get_screen_name_parsing(self):
        path_type, _ = get_property_string_expr("events", "$screen_name", "'$screen_name'", "properties")
        return path_type
