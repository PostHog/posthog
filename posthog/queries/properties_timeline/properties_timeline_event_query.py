import datetime as dt
from typing import Any, Dict, Tuple

from posthog.models.entity.util import get_entity_filtering_params
from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.event_query import EventQuery
from posthog.queries.query_date_range import QueryDateRange


class PropertiesTimelineEventQuery(EventQuery):
    effective_date_from: dt.datetime
    effective_date_to: dt.datetime

    _filter: PropertiesTimelineFilter

    def __init__(self, filter: PropertiesTimelineFilter, *args, **kwargs):
        super().__init__(filter, *args, **kwargs)

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        real_fields = [f"{self.EVENT_TABLE_ALIAS}.timestamp AS timestamp"]
        sentinel_fields = ["NULL AS timestamp"]

        for column_name in sorted(self._column_optimizer.person_on_event_columns_to_query | {"person_properties"}):
            real_fields.append(f'{self.EVENT_TABLE_ALIAS}."{column_name}" AS "{column_name}"')
            sentinel_fields.append(f"'' AS \"{column_name}\"")
        for column_name in sorted(self._column_optimizer.group_on_event_columns_to_query):
            real_fields.append(f'{self.EVENT_TABLE_ALIAS}."{column_name}" AS "{column_name}"')
            sentinel_fields.append(f"'' AS \"{column_name}\"")

        real_fields_combined = ",\n".join(real_fields)
        sentinel_fields_combined = ",\n".join(sentinel_fields)

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        entity_query, entity_params = self._get_entity_query()
        self.params.update(entity_params)

        query = f"""
            (
                SELECT {real_fields_combined}
                FROM events {self.EVENT_TABLE_ALIAS}
                WHERE
                    team_id = %(team_id)s
                    AND person_id = %(person_id)s
                    {entity_query}
                    {date_query}
                ORDER BY timestamp ASC
            ) UNION ALL (
                SELECT {sentinel_fields_combined} /* We need a final sentinel row for relevant_event_count */
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
        self.effective_date_from = query_date_range.date_from_param
        self.effective_date_to = query_date_range.date_to_param
        parsed_date_from, date_from_params = query_date_range.date_from
        parsed_date_to, date_to_params = query_date_range.date_to

        query_params.update(date_from_params)
        query_params.update(date_to_params)

        date_filter = f"{parsed_date_from} {parsed_date_to}"

        return date_filter, query_params

    def _get_entity_query(self) -> Tuple[str, Dict]:
        entity_params, entity_format_params = get_entity_filtering_params(
            allowed_entities=self._filter.entities,
            team_id=self._team_id,
            table_name=self.EVENT_TABLE_ALIAS,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS,
        )

        return entity_format_params.get("entity_query", ""), entity_params
