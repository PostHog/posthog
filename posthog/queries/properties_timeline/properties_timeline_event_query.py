from typing import Any, Dict, Tuple

from posthog.constants import DATE_TO, EXPLICIT_DATE
from posthog.models.entity.util import get_entity_filtering_params
from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.event_query import EventQuery
from posthog.queries.query_date_range import QueryDateRange


class PropertiesTimelineEventQuery(EventQuery):
    _filter: PropertiesTimelineFilter

    def __init__(self, filter: PropertiesTimelineFilter, *args, **kwargs):
        super().__init__(filter, *args, **kwargs)

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        _fields = f"{self.EVENT_TABLE_ALIAS}.timestamp as timestamp"

        for column_name in sorted(self._column_optimizer.person_on_event_columns_to_query | {"person_properties"}):
            _fields += f', {self.EVENT_TABLE_ALIAS}."{column_name}" as "{column_name}"'

        for column_name in sorted(self._column_optimizer.group_on_event_columns_to_query):
            _fields += f', {self.EVENT_TABLE_ALIAS}."{column_name}" as "{column_name}"'

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        lookback_date_query, lookback_date_params = self._get_lookback_date_filter()
        self.params.update(lookback_date_params)

        entity_query, entity_params = self._get_entity_query()
        self.params.update(entity_params)

        query = f"""
            ( /* Select a single event immediately preceding the main date range to determine pre-existing properties */
                SELECT {_fields}, true AS is_pre_range FROM events {self.EVENT_TABLE_ALIAS}
                PREWHERE
                    team_id = %(team_id)s
                    AND person_id = %(person_id)s
                    {entity_query}
                    {lookback_date_query}
                ORDER BY timestamp DESC
                LIMIT 1
            ) UNION ALL ( /* Select events from main date range */
                SELECT {_fields}, false AS is_pre_range FROM events {self.EVENT_TABLE_ALIAS}
                PREWHERE
                    team_id = %(team_id)s
                    AND person_id = %(person_id)s
                    {entity_query}
                    {date_query}
                ORDER BY timestamp ASC
            )
        """

        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
        self._should_join_distinct_ids = False

    def _determine_should_join_persons(self) -> None:
        self._should_join_persons = False

    def _determine_should_join_sessions(self) -> None:
        self._should_join_sessions = False

    def _get_date_filter(self) -> Tuple[str, Dict]:
        query_params: Dict[str, Any] = {}
        query_date_range = QueryDateRange(self._filter, self._team)
        parsed_date_from, date_from_params = query_date_range.date_from
        parsed_date_to, date_to_params = query_date_range.date_to

        query_params.update(date_from_params)
        query_params.update(date_to_params)

        date_filter = f"{parsed_date_from} {parsed_date_to}"

        return date_filter, query_params

    def _get_lookback_date_filter(self) -> Tuple[str, Dict]:
        query_date_range = QueryDateRange(
            self._filter.with_data({DATE_TO: self._filter.date_from, EXPLICIT_DATE: True}),
            self._team,
            param_prefix="lookback",
            is_right_open=True,  # Needs to be right-open so that this doesn't intersect with the main date range
        )
        return query_date_range.date_to

    def _get_entity_query(self) -> Tuple[str, Dict]:
        entity_params, entity_format_params = get_entity_filtering_params(
            allowed_entities=self._filter.entities,
            team_id=self._team_id,
            table_name=self.EVENT_TABLE_ALIAS,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self._using_person_on_events
            else PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
        )

        return entity_format_params.get("entity_query", ""), entity_params
