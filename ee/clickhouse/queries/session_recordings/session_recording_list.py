from collections import namedtuple
from typing import Any, Dict, List, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_entity_filter
from ee.clickhouse.models.entity import get_entity_filtering_params
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from posthog.models.entity import Entity
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList

EventFiltersSQL = namedtuple(
    "EventFiltersSQL",
    ["event_select_clause", "event_where_clause", "aggregate_select_clause", "aggregate_where_clause", "params"],
)


class ClickhouseSessionRecordingList(SessionRecordingList):
    _core_session_recording_query: str = """
        SELECT
            all_recordings.session_id,
            all_recordings.start_time,
            all_recordings.end_time,
            all_recordings.duration,
            person_distinct_id.person_id
        FROM(
            SELECT
                session_id,
                any(distinct_id) as distinct_id,
                MIN(timestamp) AS start_time,
                MAX(timestamp) AS end_time,
                dateDiff('second', toDateTime(MIN(timestamp)), toDateTime(MAX(timestamp))) as duration,
                COUNT((JSONExtractInt(snapshot_data, 'type') = 2 OR JSONExtractBool(snapshot_data, 'has_full_snapshot')) ? 1 : NULL) as full_snapshots
            FROM session_recording_events
            WHERE
                team_id = %(team_id)s
                {events_timestamp_clause}
            GROUP BY session_id
        ) as all_recordings
        JOIN person_distinct_id 
            ON person_distinct_id.distinct_id = all_recordings.distinct_id
        WHERE full_snapshots > 0
        AND person_distinct_id.team_id = %(team_id)s
        {recording_start_time_clause}
        {duration_clause}
        {person_id_clause} 
    """

    _limited_session_recordings_query: str = """
    {core_session_recording_query}
    ORDER BY start_time DESC
    LIMIT %(limit)s OFFSET %(offset)s
    """

    _session_recordings_query_with_entity_filter: str = """
    SELECT * FROM
    (
        SELECT
            session_recordings.session_id,
            any(session_recordings.start_time) as start_time,
            any(session_recordings.end_time) as end_time,
            any(session_recordings.duration) as duration,
            any(person_distinct_id.person_id) as person_id
            {event_filter_aggregate_select_clause}
        FROM (
            SELECT
            timestamp,
            distinct_id
            {event_filter_event_select_clause}
            FROM events
            WHERE
                team_id = %(team_id)s
                {events_timestamp_clause}
                {event_filter_event_where_clause}
        ) AS filtered_events
        JOIN person_distinct_id ON person_distinct_id.distinct_id = filtered_events.distinct_id
        JOIN (
            {core_session_recording_query}
        ) AS session_recordings
        ON session_recordings.person_id = person_distinct_id.person_id
        WHERE
            filtered_events.timestamp >= session_recordings.start_time 
            AND filtered_events.timestamp <= session_recordings.end_time
        GROUP BY session_recordings.session_id
    ) as session_recordings
    {event_filter_aggregate_where_clause}
    ORDER BY start_time DESC
    LIMIT %(limit)s OFFSET %(offset)s
    """

    def _get_entity_clause(self):
        entity_params, entity_clause = {}, ""
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

    def _get_duration_clause(self):
        duration_clause = ""
        duration_params = {}
        if self._filter.recording_duration_filter:
            if self._filter.recording_duration_filter.operator == "gt":
                operator = ">"
            else:
                operator = "<"
            duration_clause = f"AND duration {operator} %(recording_duration)s"
            duration_params = {
                "recording_duration": self._filter.recording_duration_filter.value,
            }
        return duration_params, duration_clause

    def _get_person_id_clause(self):
        person_id_clause = ""
        person_id_params = {}
        if self._filter.person_uuid:
            person_id_clause = f"AND person_distinct_id.person_id = %(person_uuid)s"
            person_id_params = {"person_uuid": self._filter.person_uuid}
        return person_id_params, person_id_clause

    def _build_query(self) -> Tuple[str, Dict]:
        params = {"team_id": self._team.pk, "limit": self.SESSION_RECORDINGS_DEFAULT_LIMIT, "offset": 0}
        events_timestamp_params, events_timestamp_clause = self._get_events_timestamp_clause()
        recording_start_time_params, recording_start_time_clause = self._get_recording_start_time_clause()
        person_id_params, person_id_clause = self._get_person_id_clause()
        duration_params, duration_clause = self._get_duration_clause()
        core_session_recording_query = self._core_session_recording_query.format(
            person_id_clause=person_id_clause,
            events_timestamp_clause=events_timestamp_clause,
            recording_start_time_clause=recording_start_time_clause,
            duration_clause=duration_clause,
        )
        if self._has_entity_filters():
            event_filters = format_event_filters(self._filter)

            return (
                self._session_recordings_query_with_entity_filter.format(
                    core_session_recording_query=core_session_recording_query,
                    person_id_clause=person_id_clause,
                    events_timestamp_clause=events_timestamp_clause,
                    recording_start_time_clause=recording_start_time_clause,
                    event_filter_event_select_clause=event_filters.event_select_clause,
                    event_filter_event_where_clause=event_filters.event_where_clause,
                    event_filter_aggregate_select_clause=event_filters.aggregate_select_clause,
                    event_filter_aggregate_where_clause=event_filters.aggregate_where_clause,
                ),
                {
                    **params,
                    **person_id_params,
                    **events_timestamp_params,
                    **duration_params,
                    **event_filters.params,
                    **recording_start_time_params,
                },
            )
        return (
            self._limited_session_recordings_query.format(
                core_session_recording_query=core_session_recording_query,
                person_id_clause=person_id_clause,
                events_timestamp_clause=events_timestamp_clause,
                recording_start_time_clause=recording_start_time_clause,
            ),
            {
                **params,
                **person_id_params,
                **events_timestamp_params,
                **duration_params,
                **recording_start_time_params,
            },
        )

    def data_to_return(self, results: List[Any]) -> List[Dict[str, Any]]:
        return [dict(zip(["session_id", "start_time", "end_time", "duration", "person_id"], row)) for row in results]

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        query, query_params = self._build_query()
        results = sync_execute(query, query_params)
        return self.data_to_return(results)


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
