from typing import Any, Dict, List, NamedTuple, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_entity_filter
from ee.clickhouse.models.entity import get_entity_filtering_params
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from posthog.models.entity import Entity
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.queries.session_recordings.session_recording_list import (
    EventsQueryWithAggregateClausesSQL,
    SessionRecordingList,
)


class EventFiltersSQL(NamedTuple):
    event_select_clause: str
    event_where_clause: str
    aggregate_select_clause: str
    aggregate_where_clause: str
    params: Dict[str, Any]


class ClickhouseSessionRecordingList(SessionRecordingList):
    _duration_filter_clause = "AND duration {operator} %(recording_duration)s"
    _recording_duration_select_statement = (
        "dateDiff('second', toDateTime(MIN(timestamp)), toDateTime(MAX(timestamp))) as duration,"
    )
    _recording_full_snapshot_select_statement = "COUNT((JSONExtractInt(snapshot_data, 'type') = 2 OR JSONExtractBool(snapshot_data, 'has_full_snapshot')) ? 1 : NULL) as full_snapshots"
    _session_recording_event_table = "session_recording_events"

    _event_query = """
        SELECT
            timestamp,
            distinct_id
            {event_filter_event_select_clause}
        FROM events
        WHERE
            team_id = %(team_id)s
            {events_timestamp_clause}
            {event_filter_event_where_clause}
    """

    def _get_entity_clause(self) -> Tuple[Dict[str, Any], str]:
        entity_clause = ""
        entity_params: Dict[str, Any] = {}
        if self._has_entity_filters():
            entity = self._filter.entities[0]
            entity_params, entity_content_sql_params = get_entity_filtering_params(
                entity,
                self._team.pk,
                table_name="events",
                person_properties_column=ClickhousePersonQuery.PERSON_PROPERTIES_ALIAS,
                with_prop_filters=True,
            )
            entity_clause = entity_content_sql_params.get("entity_query", "")
        return entity_params, entity_clause

    def _get_distinct_id_clause(self) -> Tuple[Dict[str, Any], str]:
        distinct_id_clause = ""
        distinct_id_params = {}
        if self._filter.person_uuid:
            distinct_id_clause = (
                f"AND distinct_id IN (SELECT distinct_id from person_distinct_id WHERE person_id = %(person_uuid)s)"
            )
            distinct_id_params = {"person_uuid": self._filter.person_uuid}
        return distinct_id_params, distinct_id_clause

    def _get_events_query_with_aggregate_clauses(self) -> EventsQueryWithAggregateClausesSQL:
        event_filters = format_event_filters(self._filter)
        events_timestamp_params, events_timestamp_clause = self._get_events_timestamp_clause()
        event_query = self._event_query.format(
            events_timestamp_clause=events_timestamp_clause,
            event_filter_event_select_clause=event_filters.event_select_clause,
            event_filter_event_where_clause=event_filters.event_where_clause,
        )

        params: Dict[str, Any] = {"team_id": self._team.pk, **events_timestamp_params, **event_filters.params}

        return EventsQueryWithAggregateClausesSQL(
            event_query, params, event_filters.aggregate_select_clause, event_filters.aggregate_where_clause,
        )

    def _build_query(self) -> Tuple[str, Dict]:
        query, params = super()._build_query()
        # Clickhouse is case sensitive on 'any()'
        query = query.replace("ANY(", "any(")
        return query, params

    def data_to_return(self, results: List[Any]) -> List[Dict[str, Any]]:
        return [dict(zip(["session_id", "start_time", "end_time", "duration", "distinct_id"], row)) for row in results]

    def run(self, *args, **kwargs) -> Tuple[Dict[str, Any], bool]:
        query, query_params = self._build_query()
        results = sync_execute(query, query_params)
        results = self.data_to_return(results)
        return self._paginate_results(results)


def format_event_filters(filter: SessionRecordingsFilter) -> EventFiltersSQL:
    if len(filter.event_and_action_filters) == 0:
        return EventFiltersSQL("", "", "", "", {})

    event_select_clause = ""
    aggregate_select_clause = ""
    aggregate_where_conditions = []
    event_where_conditions = []

    params: Dict = {}

    for index, entity in enumerate(filter.event_and_action_filters):
        condition_sql, filter_params = format_event_filter(entity, prepend=f"event_matcher_{index}")

        event_select_clause += f", if({condition_sql}, 1, 0) as event_match_{index}"
        aggregate_select_clause += f", sum(event_match_{index}) as count_event_match_{index}"
        aggregate_where_conditions.append(f"count_event_match_{index} > 0")
        event_where_conditions.append(condition_sql)
        params = {**params, **filter_params}

    aggregate_where_clause = f"WHERE {' AND '.join(aggregate_where_conditions)}"
    event_where_clause = f"AND ({' OR '.join(event_where_conditions)})"

    return EventFiltersSQL(
        event_select_clause, event_where_clause, aggregate_select_clause, aggregate_where_clause, params,
    )


def format_event_filter(entity: Entity, prepend: str):
    filter_sql, params = format_entity_filter(entity, prepend=prepend, filter_by_team=False)
    if entity.properties:
        filters, filter_params = parse_prop_clauses(
            entity.properties, prepend=prepend, team_id=None, allow_denormalized_props=False
        )
        filter_sql += f" {filters}"
        params = {**params, **filter_params}

    return filter_sql, params
