import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from posthog.models.entity.util import get_entity_filtering_params
from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.queries.event_query import EventQuery
from posthog.queries.query_date_range import QueryDateRange
from posthog.queries.util import PersonPropertiesMode


class PropertiesTimelineEventQuery(EventQuery):
    effective_date_from: dt.datetime
    effective_date_to: dt.datetime

    _filter: PropertiesTimelineFilter

    def get_query(self) -> tuple[str, dict[str, Any]]:
        real_fields = [f"{self.EVENT_TABLE_ALIAS}.timestamp AS timestamp"]
        sentinel_fields = ["NULL AS timestamp"]

        columns_to_query = self._column_optimizer.person_on_event_columns_to_query | {"person_properties"}

        for column_name in sorted(columns_to_query):
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
                    AND person_id = %(actor_id)s
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

    def _get_date_filter(self) -> tuple[str, dict]:
        query_params: dict[str, Any] = {}
        query_date_range = QueryDateRange(self._filter, self._team)
        effective_timezone = ZoneInfo(self._team.timezone)
        # Get effective date range from QueryDateRange
        # We need to explicitly replace tzinfo in those datetimes with the team's timezone, because QueryDateRange
        # does not reliably make those datetimes timezone-aware. That's annoying, but it'd be a significant effort
        # to refactor QueryDateRange fo full timezone awareness - before that happens, it's simpler to override here.
        self.effective_date_from = query_date_range.date_from_param.replace(tzinfo=effective_timezone)
        self.effective_date_to = query_date_range.date_to_param.replace(tzinfo=effective_timezone)
        parsed_date_from, date_from_params = query_date_range.date_from
        parsed_date_to, date_to_params = query_date_range.date_to

        query_params.update(date_from_params)
        query_params.update(date_to_params)

        date_filter = f"{parsed_date_from} {parsed_date_to}"

        return date_filter, query_params

    def _get_entity_query(self) -> tuple[str, dict]:
        entity_params, entity_format_params = get_entity_filtering_params(
            allowed_entities=self._filter.entities,
            team_id=self._team_id,
            table_name=self.EVENT_TABLE_ALIAS,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS,
            hogql_context=self._filter.hogql_context,
        )

        return entity_format_params.get("entity_query", ""), entity_params
