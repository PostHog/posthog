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

ActionFiltersSQL = namedtuple(
    "ActionFiltersSQL", ["select_clause", "matches_action_clauses", "filters_having", "matches_any_clause", "params"]
)


class ClickhouseSessionRecordingList(SessionRecordingList):
    _core_session_recording_query: str = """
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
            {distinct_id_clause}
            {timestamp_clause}
        GROUP BY session_id, distinct_id
        HAVING full_snapshots > 0
        {duration_clause}
        ORDER BY start_time DESC
    """

    _basic_session_recordings_query: str = """
    SELECT
        session_id,
        distinct_id,
        start_time,
        end_time,
        duration
    FROM (
        {core_session_recording_query}
    )
    LIMIT %(limit)s OFFSET %(offset)s
    """

    _session_recordings_query_with_entity_filter: str = """
    SELECT
        session_recordings.session_id,
        MIN(session_recordings.distinct_id) as distinct_id,
        MIN(session_recordings.start_time) as start_time,
        MIN(session_recordings.end_time) as end_time,
        MIN(session_recordings.duration) as duration
        {filters_select_clause}
    FROM (
        {core_session_recording_query}
    ) as session_recordings
    JOIN (
        SELECT
        timestamp,
        distinct_id
        {matches_action_clauses}
        FROM events
        WHERE
            team_id = %(team_id)s
            {distinct_id_clause}
            {timestamp_clause}
    ) as filtered_events on (filtered_events.distinct_id = session_recordings.distinct_id)
    WHERE
        filtered_events.timestamp >= session_recordings.start_time 
        AND filtered_events.timestamp <= session_recordings.end_time
    GROUP BY session_recordings.session_id
    {filters_having}
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

    def _build_query(self) -> Tuple[str, Dict]:
        params = {"team_id": self._team.pk, "limit": self.SESSION_RECORDINGS_DEFAULT_LIMIT, "offset": 0}
        timestamp_params, timestamp_clause = self._get_timestamp_clause()
        distinct_id_params, distinct_id_clause = self._get_distinct_id_clause()
        duration_params, duration_clause = self._get_duration_clause()
        core_session_recording_query = self._core_session_recording_query.format(
            distinct_id_clause=distinct_id_clause, timestamp_clause=timestamp_clause, duration_clause=duration_clause
        )
        if self._has_entity_filters():
            action_filters = format_action_filters(self._filter)

            return (
                self._session_recordings_query_with_entity_filter.format(
                    core_session_recording_query=core_session_recording_query,
                    distinct_id_clause=distinct_id_clause,
                    timestamp_clause=timestamp_clause,
                    filters_select_clause=action_filters.select_clause,
                    matches_action_clauses=action_filters.matches_action_clauses,
                    filters_having=action_filters.filters_having,
                ),
                {**params, **distinct_id_params, **timestamp_params, **duration_params, **action_filters.params,},
            )
        return (
            self._basic_session_recordings_query.format(
                core_session_recording_query=core_session_recording_query,
                distinct_id_clause=distinct_id_clause,
                timestamp_clause=timestamp_clause,
            ),
            {**params, **distinct_id_params, **timestamp_params, **duration_params},
        )

    def data_to_return(self, results: List[Any]) -> List[Dict[str, Any]]:
        return [dict(zip(["session_id", "distinct_id", "start_time", "end_time", "duration"], row)) for row in results]

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        query, query_params = self._build_query()
        results = sync_execute(query, query_params)
        return self.data_to_return(results)


def format_action_filters(filter: SessionRecordingsFilter) -> ActionFiltersSQL:
    if len(filter.event_and_action_filters) == 0:
        return ActionFiltersSQL("", "", "", "", {})

    matches_action_clauses = select_clause = ""
    having_clause = []
    matches_any_clause = []

    params: Dict = {}

    for index, entity in enumerate(filter.event_and_action_filters):
        condition_sql, filter_params = format_action_filter_aggregate(entity, prepend=f"event_matcher_{index}")

        matches_action_clauses += f", ({condition_sql}) ? uuid : NULL as event_match_{index}"
        select_clause += f", groupArray(event_match_{index}) as event_match_{index}"
        having_clause.append(f"notEmpty(event_match_{index})")
        matches_any_clause.append(condition_sql)

        params = {**params, **filter_params}

    return ActionFiltersSQL(
        select_clause,
        matches_action_clauses,
        f"HAVING {' AND '.join(having_clause)}",
        f"AND ({' OR '.join(matches_any_clause)})",
        params,
    )


def format_action_filter_aggregate(entity: Entity, prepend: str):
    filter_sql, params = format_entity_filter(entity, prepend=prepend, filter_by_team=False)
    if entity.properties:
        filters, filter_params = parse_prop_clauses(
            entity.properties, prepend=prepend, team_id=None, allow_denormalized_props=False
        )
        filter_sql += f" {filters}"
        params = {**params, **filter_params}

    return filter_sql, params
