from datetime import timedelta
from typing import Any, Dict, List, NamedTuple, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_entity_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.models.util import PersonPropertiesMode
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from posthog.models.entity import Entity
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList, SessionRecordingQueryResult


class EventFiltersSQL(NamedTuple):
    aggregate_select_clause: str
    aggregate_having_clause: str
    params: Dict[str, Any]


class ClickhouseSessionRecordingList(SessionRecordingList):
    _session_recordings_query_with_entity_filter: str = """
    SELECT
        session_recordings.session_id,
        any(session_recordings.start_time) as start_time,
        any(session_recordings.end_time) as end_time,
        any(session_recordings.duration) as duration,
        any(session_recordings.distinct_id) as distinct_id,
        arrayElement(groupArray(current_url), 1) as start_url,
        arrayElement(groupArray(current_url), -1) as end_url
        {event_filter_aggregate_select_clause}
    FROM (
        SELECT
            distinct_id,
            event,
            team_id,
            timestamp,
            properties,
            JSONExtractString(properties, '$current_url') as current_url
        FROM events
        WHERE
            team_id = %(team_id)s
            {events_timestamp_clause}
    ) AS filtered_events
    RIGHT OUTER JOIN (
        SELECT
            session_id,
            MIN(timestamp) AS start_time,
            MAX(timestamp) AS end_time,
            dateDiff('second', toDateTime(MIN(timestamp)), toDateTime(MAX(timestamp))) as duration,
            any(distinct_id) as distinct_id,
            COUNT((JSONExtractInt(snapshot_data, 'type') = 2 OR JSONExtractBool(snapshot_data, 'has_full_snapshot')) ? 1 : NULL) as full_snapshots
        FROM session_recording_events
        WHERE
            team_id = %(team_id)s
            {events_timestamp_clause}
        GROUP BY session_id
        HAVING full_snapshots > 0
        {recording_start_time_clause}
        {duration_clause} 
    ) AS session_recordings
    ON session_recordings.distinct_id = filtered_events.distinct_id
    JOIN (
        SELECT * FROM person_distinct_id WHERE person_distinct_id.team_id = %(team_id)s
    ) as person_distinct_id 
    ON person_distinct_id.distinct_id = session_recordings.distinct_id
    JOIN ({person_query}) as person ON person.id = person_distinct_id.person_id 
    WHERE
        empty(filtered_events.event) OR
        (
            filtered_events.timestamp >= session_recordings.start_time
            AND filtered_events.timestamp <= session_recordings.end_time
        )
        {person_id_clause}
    GROUP BY session_recordings.session_id
    {event_filter_aggregate_having_clause}
    ORDER BY start_time DESC
    LIMIT %(limit)s OFFSET %(offset)s
    """

    def _get_person_query(self,) -> Tuple[str, Dict[str, Any]]:
        return ClickhousePersonQuery(filter=self._filter, team_id=self._team.pk).get_query()

    def _has_entity_filters(self):
        return self._filter.entities and len(self._filter.entities) > 0

    def _get_limit(self):
        return self._filter.limit or self.SESSION_RECORDINGS_DEFAULT_LIMIT

    def _get_person_id_clause(self) -> Tuple[str, Dict[str, Any]]:
        person_id_clause = ""
        person_id_params = {}
        if self._filter.person_uuid:
            person_id_clause = "AND person.id = %(person_uuid)s"
            person_id_params = {"person_uuid": self._filter.person_uuid}
        return person_id_clause, person_id_params

    # We want to select events beyond the range of the recording to handle the case where
    # a recording spans the time boundaries
    def _get_events_timestamp_clause(self) -> Tuple[str, Dict[str, Any]]:
        timestamp_clause = ""
        timestamp_params = {}
        if self._filter.date_from:
            timestamp_clause += "\nAND timestamp >= %(event_start_time)s"
            timestamp_params["event_start_time"] = self._filter.date_from - timedelta(hours=12)
        if self._filter.date_to:
            timestamp_clause += "\nAND timestamp <= %(event_end_time)s"
            timestamp_params["event_end_time"] = self._filter.date_to + timedelta(hours=12)
        return timestamp_clause, timestamp_params

    def _get_recording_start_time_clause(self) -> Tuple[str, Dict[str, Any]]:
        start_time_clause = ""
        start_time_params = {}
        if self._filter.date_from:
            start_time_clause += "\nAND start_time >= %(start_time)s"
            start_time_params["start_time"] = self._filter.date_from
        if self._filter.date_to:
            start_time_clause += "\nAND start_time <= %(end_time)s"
            start_time_params["end_time"] = self._filter.date_to
        return start_time_clause, start_time_params

    def _get_duration_clause(self) -> Tuple[str, Dict[str, Any]]:
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
        return duration_clause, duration_params

    def format_event_filter(self, entity: Entity, prepend: str) -> Tuple[str, Dict[str, Any]]:
        filter_sql, params = format_entity_filter(entity, prepend=prepend, filter_by_team=False)
        if entity.properties:
            filters, filter_params = parse_prop_clauses(
                entity.properties,
                prepend=prepend,
                team_id=self._team.pk,
                allow_denormalized_props=False,
                has_person_id_joined=True,
                table_name="filtered_events",
                person_properties_mode=PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            )
            filter_sql += f" {filters}"
            params = {**params, **filter_params}

        return filter_sql, params

    def format_event_filters(self) -> EventFiltersSQL:
        if len(self._filter.entities) == 0:
            return EventFiltersSQL("", "", {})

        aggregate_select_clause = ""
        aggregate_where_conditions = []
        event_where_conditions = []

        params: Dict = {}

        for index, entity in enumerate(self._filter.entities):
            condition_sql, filter_params = self.format_event_filter(entity, prepend=f"event_matcher_{index}")
            aggregate_select_clause += f", sum(if({condition_sql}, 1, 0)) as count_event_match_{index}"
            aggregate_where_conditions.append(f"count_event_match_{index} > 0")
            event_where_conditions.append(condition_sql)
            params = {**params, **filter_params}

        aggregate_having_clause = f"HAVING {' AND '.join(aggregate_where_conditions)}"

        return EventFiltersSQL(aggregate_select_clause, aggregate_having_clause, params,)

    def _build_query(self) -> Tuple[str, Dict[str, Any]]:
        # One more is added to the limit to check if there are more results available
        limit = self._get_limit() + 1
        offset = self._filter.offset or 0
        base_params = {"team_id": self._team.pk, "limit": limit, "offset": offset}
        person_query, person_query_params = self._get_person_query()
        events_timestamp_clause, events_timestamp_params = self._get_events_timestamp_clause()
        recording_start_time_clause, recording_start_time_params = self._get_recording_start_time_clause()
        person_id_clause, person_id_params = self._get_person_id_clause()
        duration_clause, duration_params = self._get_duration_clause()
        event_filters = self.format_event_filters()

        return (
            self._session_recordings_query_with_entity_filter.format(
                person_id_clause=person_id_clause,
                person_query=person_query,
                events_timestamp_clause=events_timestamp_clause,
                recording_start_time_clause=recording_start_time_clause,
                duration_clause=duration_clause,
                event_filter_aggregate_select_clause=event_filters.aggregate_select_clause,
                event_filter_aggregate_having_clause=event_filters.aggregate_having_clause,
            ),
            {
                **base_params,
                **person_id_params,
                **person_query_params,
                **events_timestamp_params,
                **duration_params,
                **recording_start_time_params,
                **event_filters.params,
            },
        )

    def _paginate_results(self, session_recordings) -> SessionRecordingQueryResult:
        limit = self._get_limit()
        more_recordings_available = False
        if len(session_recordings) > limit:
            more_recordings_available = True
            session_recordings = session_recordings[0:limit]
        return SessionRecordingQueryResult(session_recordings, more_recordings_available)

    def _data_to_return(self, results: List[Any]) -> List[Dict[str, Any]]:
        return [
            dict(zip(["session_id", "start_time", "end_time", "duration", "distinct_id", "start_url", "end_url"], row))
            for row in results
        ]

    def run(self, *args, **kwargs) -> SessionRecordingQueryResult:
        query, query_params = self._build_query()
        query_results = sync_execute(query, query_params)
        session_recordings = self._data_to_return(query_results)
        return self._paginate_results(session_recordings)
