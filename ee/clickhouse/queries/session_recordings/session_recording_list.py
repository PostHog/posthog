from typing import Any, Dict, List, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.entity import get_entity_filtering_params
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList


class ClickhouseSessionRecordingList(SessionRecordingList):
    _basic_session_recordings_query: str = """
    SELECT
        session_id,
        distinct_id,
        start_time,
        end_time,
        dateDiff('second', toDateTime(start_time), toDateTime(end_time)) as duration
    FROM (
        SELECT
            session_id,
            distinct_id,
            MIN(timestamp) AS start_time,
            MAX(timestamp) AS end_time,
            COUNT((JSONExtractInt(snapshot_data, 'type') = 2 OR JSONExtractBool(snapshot_data, 'has_full_snapshot')) ? 1 : NULL) as full_snapshots
        FROM session_recording_events
        WHERE
                team_id = %(team_id)s
                {distinct_id_clause}
                {timestamp_clause}
        GROUP BY session_id, distinct_id
    )
    WHERE full_snapshots > 0
    ORDER BY start_time DESC
    LIMIT %(limit)s OFFSET %(offset)s
    """

    _session_recordings_query_with_entity_filter: str = """
    SELECT
        session_recordings.session_id,
        MIN(session_recordings.distinct_id) as distinct_id,
        MIN(session_recordings.start_time) as start_time,
        MIN(session_recordings.end_time) as end_time,
        dateDiff('second', toDateTime(MIN(session_recordings.start_time)), toDateTime(MIN(session_recordings.end_time))) as duration,
        count(*) as event_count
    FROM (
        SELECT
            session_id,
            distinct_id,
            MIN(timestamp) AS start_time,
            MAX(timestamp) AS end_time,
            COUNT((JSONExtractInt(snapshot_data, 'type') = 2 OR JSONExtractBool(snapshot_data, 'has_full_snapshot')) ? 1 : NULL) as full_snapshots
        FROM session_recording_events
        WHERE
                team_id = %(team_id)s
                {distinct_id_clause}
                {timestamp_clause}
        GROUP BY session_id, distinct_id
    ) as session_recordings
    JOIN (
        SELECT * FROM events
        WHERE
            team_id = %(team_id)s
            {distinct_id_clause}
            {entity_clause}
            {timestamp_clause}
    ) as filtered_events on (filtered_events.distinct_id = session_recordings.distinct_id)
    WHERE
        full_snapshots > 0
        AND filtered_events.timestamp >= session_recordings.start_time 
        AND filtered_events.timestamp <= session_recordings.end_time
    GROUP BY session_recordings.session_id
    HAVING event_count > 0
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

    def _build_query(self) -> Tuple[str, Dict]:
        params = {"team_id": self._team.pk, "limit": self.SESSION_RECORDINGS_DEFAULT_LIMIT, "offset": 0}
        timestamp_params, timestamp_clause = self._get_timestamp_clause()
        distinct_id_params, distinct_id_clause = self._get_distinct_id_clause()

        if self._has_entity_filters():
            entity_params, entity_clause = self._get_entity_clause()
            return (
                self._session_recordings_query_with_entity_filter.format(
                    distinct_id_clause=distinct_id_clause,
                    entity_clause=entity_clause,
                    timestamp_clause=timestamp_clause,
                ),
                {**params, **distinct_id_params, **entity_params, **timestamp_params},
            )
        return (
            self._basic_session_recordings_query.format(
                distinct_id_clause=distinct_id_clause, timestamp_clause=timestamp_clause,
            ),
            {**params, **distinct_id_params, **timestamp_params},
        )

    def data_to_return(self, results: List[Any]) -> List[Dict[str, Any]]:
        return [dict(zip(["session_id", "distinct_id", "start_time", "end_time", "duration"], row)) for row in results]

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        query, query_params = self._build_query()
        results = sync_execute(query, query_params)
        return self.data_to_return(results)
