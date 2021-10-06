from datetime import timedelta
from typing import Any, Dict, List, Tuple

from django.db import connection
from django.db.models import Q, QuerySet
from django.db.models.expressions import ExpressionWrapper
from django.db.models.fields import BooleanField

from posthog.models import Event, Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.person import Person
from posthog.models.utils import namedtuplefetchall, sane_repr
from posthog.queries.base import BaseQuery, entity_to_Q


class SessionRecordingList(BaseQuery):
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50
    _filter: SessionRecordingsFilter
    _team: Team

    def __init__(self, filter: SessionRecordingsFilter, team: Team) -> None:
        self._filter = filter
        self._team = team

    _duration_filter_clause = "AND duration {operator} INTERVAL '%(recording_duration)s seconds'"
    _recording_duration_select_statement = "MAX(timestamp) - MIN(timestamp) as duration,"
    _recording_full_snapshot_select_statement = "COUNT(*) FILTER(where snapshot_data->>'type' = '2' OR (snapshot_data->>'has_full_snapshot')::boolean) as full_snapshots"
    _session_recording_event_table = "posthog_sessionrecordingevent"

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
                {recording_duration_select_statement}
                {recording_full_snapshot_select_statement}
            FROM {session_recording_event_table}
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
            ANY(session_recordings.start_time) as start_time,
            ANY(session_recordings.end_time) as end_time,
            ANY(session_recordings.duration) as duration,
            ANY(filtered_events.distinct_id) as distinct_id
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

    def _has_entity_filters(self):
        return self._filter.entities and len(self._filter.entities) > 0

    def _get_limit(self):
        return self._filter.limit or self.SESSION_RECORDINGS_DEFAULT_LIMIT

    # We want to select events beyond the range of the recording to handle the case where
    # a recording spans the time boundaries
    def _get_events_timestamp_clause(self):
        timestamp_clause = ""
        timestamp_params = {}
        if self._filter.date_from:
            timestamp_clause += "\nAND timestamp >= %(event_start_time)s"
            timestamp_params["event_start_time"] = self._filter.date_from - timedelta(hours=12)
        if self._filter.date_to:
            timestamp_clause += "\nAND timestamp <= %(event_end_time)s"
            timestamp_params["event_end_time"] = self._filter.date_to + timedelta(hours=12)
        return timestamp_params, timestamp_clause

    def _get_recording_start_time_clause(self):
        start_time_clause = ""
        start_time_params = {}
        if self._filter.date_from:
            start_time_clause += "\nAND start_time >= %(start_time)s"
            start_time_params["start_time"] = self._filter.date_from
        if self._filter.date_to:
            start_time_clause += "\nAND start_time <= %(end_time)s"
            start_time_params["end_time"] = self._filter.date_to
        return start_time_params, start_time_clause

    def _get_distinct_id_clause(self):
        distinct_id_clause = ""
        distinct_id_params = {}
        if self._filter.person_uuid:
            person = Person.objects.get(uuid=self._filter.person_uuid)
            distinct_id_clause = (
                f"AND distinct_id IN (SELECT distinct_id from posthog_persondistinctid WHERE person_id = %(person_id)s)"
            )
            distinct_id_params = {"person_id": person.pk}
        return distinct_id_params, distinct_id_clause

    def _get_duration_clause(self):
        duration_clause = ""
        duration_params = {}
        if self._filter.recording_duration_filter:
            if self._filter.recording_duration_filter.operator == "gt":
                operator = ">"
            else:
                operator = "<"
            duration_clause = self._duration_filter_clause.format(operator=operator)
            duration_params = {
                "recording_duration": self._filter.recording_duration_filter.value,
            }
        return duration_params, duration_clause

    def _get_events_query(self) -> QuerySet:
        events = Event.objects.filter(team=self._team).order_by("-timestamp").only("distinct_id", "timestamp")
        if self._filter.date_from:
            events = events.filter(timestamp__gte=self._filter.date_from - timedelta(hours=12))
        if self._filter.date_to:
            events = events.filter(timestamp__lte=self._filter.date_to + timedelta(hours=12))

        keys = []
        event_q_filters = []

        for i, entity in enumerate(self._filter.event_and_action_filters):
            key = f"entity_{i}"
            q_filter = entity_to_Q(entity, self._team.pk)
            event_q_filters.append(q_filter)
            events = events.annotate(**{key: ExpressionWrapper(q_filter, output_field=BooleanField())})
            keys.append(key)

        combined_event_q_filter = Q()
        for events_q_filter in event_q_filters:
            combined_event_q_filter |= events_q_filter

        events = events.filter(combined_event_q_filter)
        events = events.values_list("distinct_id", "timestamp", *keys)

        with connection.cursor() as cursor:
            event_query = cursor.mogrify(*events.query.sql_with_params()).decode("utf-8")

        return event_query, keys

    def _get_events_query_with_aggregate_clauses(self):
        event_query, keys = self._get_events_query()
        aggregate_select_clause = ""
        aggregate_having_conditions = []
        for key in keys:
            aggregate_field_name = f"count_{key}"
            aggregate_select_clause += f", SUM(CASE WHEN {key} THEN 1 ELSE 0 END) as {aggregate_field_name}"
            aggregate_having_conditions.append(f"{aggregate_field_name} > 0")

        aggregate_where_clause = f"WHERE {' AND '.join(aggregate_having_conditions)}"

        return (event_query, {}, aggregate_select_clause, aggregate_where_clause)

    def _build_query(self) -> Tuple[str, Dict]:
        # One more is added to the limit to check if there are more results available
        limit = self._get_limit() + 1
        offset = self._filter.offset or 0
        base_params = {"team_id": self._team.pk, "limit": limit, "offset": offset}
        events_timestamp_params, events_timestamp_clause = self._get_events_timestamp_clause()
        recording_start_time_params, recording_start_time_clause = self._get_recording_start_time_clause()
        distinct_id_params, distinct_id_clause = self._get_distinct_id_clause()
        duration_params, duration_clause = self._get_duration_clause()

        core_session_recording_query = self._core_session_recording_query.format(
            recording_duration_select_statement=self._recording_duration_select_statement,
            recording_full_snapshot_select_statement=self._recording_full_snapshot_select_statement,
            session_recording_event_table=self._session_recording_event_table,
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

    def data_to_return(self, results: List[Any]) -> List[Dict[str, Any]]:
        return [row._asdict() for row in results]

    def _paginate_results(self, results):
        limit = self._get_limit()
        more_recordings_available = False
        if len(results) > limit:
            more_recordings_available = True
            results = results[0:limit]
        return (results, more_recordings_available)

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        with connection.cursor() as cursor:
            query, query_params = self._build_query()
            cursor.execute(query, query_params)
            results = namedtuplefetchall(cursor)
        results = self.data_to_return(results)
        return self._paginate_results(results)

    __repr__ = sane_repr("_team", "_filter")
