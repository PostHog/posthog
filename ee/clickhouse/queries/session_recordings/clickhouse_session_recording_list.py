from datetime import timedelta
from typing import Any, Dict, List, NamedTuple, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_entity_filter
from ee.clickhouse.models.entity import get_entity_filtering_params
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from posthog.models import Person
from posthog.models.entity import Entity
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.queries.session_recordings.session_recording_list import (
    EventsQueryWithAggregateClausesSQL,
    SessionRecordingList,
    SessionRecordingQueryResult,
)


class EventFiltersSQL(NamedTuple):
    event_select_clause: str
    event_where_clause: str
    aggregate_select_clause: str
    aggregate_where_clause: str
    params: Dict[str, Any]


class ClickhouseSessionRecordingList(SessionRecordingList):

    _core_session_recording_query: str = """
        SELECT 
            all_recordings.session_id,
            all_recordings.start_time,
            all_recordings.end_time,
            all_recordings.duration,
            all_recordings.distinct_id
        FROM (
            SELECT
                session_id,
                distinct_id,
                MIN(timestamp) AS start_time,
                MAX(timestamp) AS end_time,
                dateDiff('second', toDateTime(MIN(timestamp)), toDateTime(MAX(timestamp))) as duration,
                COUNT((JSONExtractInt(snapshot_data, 'type') = 2 OR JSONExtractBool(snapshot_data, 'has_full_snapshot')) ? 1 : NULL) as full_snapshots
            FROM session_recording_events
            WHERE
                team_id = %(team_id)s
                {events_timestamp_clause}
                {distinct_id_clause}
            GROUP BY session_id, distinct_id
        ) as all_recordings
        WHERE full_snapshots > 0
        {recording_start_time_clause}
        {duration_clause} 
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
            any(filtered_events.distinct_id) as distinct_id
            {event_filter_aggregate_select_clause}
        FROM (
            {events_query}
        ) AS filtered_events
        JOIN (
            {core_session_recording_query}
        ) AS session_recordings
        ON session_recordings.distinct_id = filtered_events.distinct_id
        WHERE
            filtered_events.timestamp >= session_recordings.start_time 
            AND filtered_events.timestamp <= session_recordings.end_time
        GROUP BY session_recordings.session_id
    ) as session_recordings
    {event_filter_aggregate_where_clause}
    ORDER BY start_time DESC
    LIMIT %(limit)s OFFSET %(offset)s
    """

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

    def _get_distinct_id_clause(self) -> Tuple[Dict[str, Any], str]:
        distinct_id_clause = ""
        distinct_id_params = {}
        if self._filter.person_uuid:
            distinct_id_clause = f"AND distinct_id IN (SELECT distinct_id from person_distinct_id WHERE person_id = %(person_uuid)s AND team_id = %(team_id)s)"
            distinct_id_params = {"person_uuid": self._filter.person_uuid, "team_id": self._team.pk}
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

    def _has_entity_filters(self):
        return self._filter.entities and len(self._filter.entities) > 0

    def _get_limit(self):
        return self._filter.limit or self.SESSION_RECORDINGS_DEFAULT_LIMIT

    # We want to select events beyond the range of the recording to handle the case where
    # a recording spans the time boundaries
    def _get_events_timestamp_clause(self) -> Tuple[Dict[str, Any], str]:
        timestamp_clause = ""
        timestamp_params = {}
        if self._filter.date_from:
            timestamp_clause += "\nAND timestamp >= %(event_start_time)s"
            timestamp_params["event_start_time"] = self._filter.date_from - timedelta(hours=12)
        if self._filter.date_to:
            timestamp_clause += "\nAND timestamp <= %(event_end_time)s"
            timestamp_params["event_end_time"] = self._filter.date_to + timedelta(hours=12)
        return timestamp_params, timestamp_clause

    def _get_recording_start_time_clause(self) -> Tuple[Dict[str, Any], str]:
        start_time_clause = ""
        start_time_params = {}
        if self._filter.date_from:
            start_time_clause += "\nAND start_time >= %(start_time)s"
            start_time_params["start_time"] = self._filter.date_from
        if self._filter.date_to:
            start_time_clause += "\nAND start_time <= %(end_time)s"
            start_time_params["end_time"] = self._filter.date_to
        return start_time_params, start_time_clause

    def _get_distinct_id_clause(self) -> Tuple[Dict[str, Any], str]:
        distinct_id_clause = ""
        distinct_id_params = {}
        if self._filter.person_uuid:
            person = Person.objects.get(uuid=self._filter.person_uuid)
            distinct_id_clause = f"AND distinct_id IN (SELECT distinct_id from posthog_persondistinctid WHERE person_id = %(person_id)s AND team_id = %(team_id)s)"
            distinct_id_params = {"person_id": person.pk, "team_id": self._team.pk}
        return distinct_id_params, distinct_id_clause

    def _get_duration_clause(self) -> Tuple[Dict[str, Any], str]:
        duration_clause = ""
        duration_params = {}
        if self._filter.recording_duration_filter:
            if self._filter.recording_duration_filter.operator == "gt":
                operator = ">"
            else:
                operator = "<"
            duration_clause = "\nAND duration {operator} %(recording_duration)s".format(operator=operator)
            duration_params = {
                "recording_duration": self._filter.recording_duration_filter.value,
            }
        return duration_params, duration_clause

    def _build_query(self) -> Tuple[str, Dict[str, Any]]:
        # One more is added to the limit to check if there are more results available
        limit = self._get_limit() + 1
        offset = self._filter.offset or 0
        base_params = {"team_id": self._team.pk, "limit": limit, "offset": offset}
        events_timestamp_params, events_timestamp_clause = self._get_events_timestamp_clause()
        recording_start_time_params, recording_start_time_clause = self._get_recording_start_time_clause()
        distinct_id_params, distinct_id_clause = self._get_distinct_id_clause()
        duration_params, duration_clause = self._get_duration_clause()

        core_session_recording_query = self._core_session_recording_query.format(
            distinct_id_clause=distinct_id_clause,
            events_timestamp_clause=events_timestamp_clause,
            recording_start_time_clause=recording_start_time_clause,
            duration_clause=duration_clause,
        )
        params = {
            **base_params,
            **distinct_id_params,
            **events_timestamp_params,
            **duration_params,
            **recording_start_time_params,
        }

        if self._has_entity_filters():
            (
                events_query,
                event_query_params,
                aggregate_select_clause,
                aggregate_where_clause,
            ) = self._get_events_query_with_aggregate_clauses()
            return (
                self._session_recordings_query_with_entity_filter.format(
                    core_session_recording_query=core_session_recording_query,
                    events_query=events_query,
                    event_filter_aggregate_select_clause=aggregate_select_clause,
                    event_filter_aggregate_where_clause=aggregate_where_clause,
                ),
                {**params, **event_query_params},
            )
        return (
            self._limited_session_recordings_query.format(core_session_recording_query=core_session_recording_query),
            params,
        )

    def _paginate_results(self, session_recordings) -> SessionRecordingQueryResult:
        limit = self._get_limit()
        more_recordings_available = False
        if len(session_recordings) > limit:
            more_recordings_available = True
            session_recordings = session_recordings[0:limit]
        return SessionRecordingQueryResult(session_recordings, more_recordings_available)

    def _data_to_return(self, results: List[Any]) -> List[Dict[str, Any]]:
        return [dict(zip(["session_id", "start_time", "end_time", "duration", "distinct_id"], row)) for row in results]

    def run(self, *args, **kwargs) -> SessionRecordingQueryResult:
        query, query_params = self._build_query()
        query_results = sync_execute(query, query_params)
        session_recordings = self._data_to_return(query_results)
        return self._paginate_results(session_recordings)


def format_event_filters(filter: SessionRecordingsFilter) -> EventFiltersSQL:
    if len(filter.entities) == 0:
        return EventFiltersSQL("", "", "", "", {})

    event_select_clause = ""
    aggregate_select_clause = ""
    aggregate_where_conditions = []
    event_where_conditions = []

    params: Dict = {}

    for index, entity in enumerate(filter.entities):
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
