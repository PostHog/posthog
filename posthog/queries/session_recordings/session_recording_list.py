import dataclasses
from datetime import timedelta
from typing import Any, Dict, List, NamedTuple, Tuple, Union

from posthog.client import sync_execute
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models import Entity
from posthog.models.action.util import format_entity_filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.models.team import PersonOnEventsMode
from posthog.queries.event_query import EventQuery
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.util import PersonPropertiesMode


@dataclasses.dataclass(frozen=True)
class EventFiltersSQL:
    non_aggregate_select_condition_clause: str
    aggregate_event_select_clause: str
    aggregate_select_clause: str
    aggregate_having_clause: str
    where_conditions: str
    params: Dict[str, Any]


class SessionRecordingQueryResult(NamedTuple):
    results: List
    has_more_recording: bool


class SessionRecordingList(EventQuery):
    _filter: SessionRecordingsFilter
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50

    _core_events_query = """
        SELECT
            uuid,
            distinct_id,
            event,
            team_id,
            timestamp,
            "$session_id" AS session_id,
            "$window_id" AS window_id
            {properties_select_clause}
        FROM events
        WHERE
            team_id = %(team_id)s
            {event_filter_where_conditions}
            {events_timestamp_clause}
    """

    _event_and_recording_match_conditions_clause = """
        (
            -- If there is a session_id on the event, then it is from posthog-js
            -- and we should use the session_id to match the recording
            (
                notEmpty(events.session_id) AND
                events.session_id == session_recordings.session_id
            ) OR
            -- If there's no session_id on the event, then it is either older data or
            -- from a posthog-client that doesn't support session (e.g. backend client)
            -- and we should match on timestamp
            (
                empty(events.session_id) AND
                (
                    events.timestamp >= session_recordings.start_time
                    AND events.timestamp <= session_recordings.end_time
                )
            )
        )
    """

    _core_session_recordings_query = """
        SELECT
            session_id,
            any(window_id) as window_id,
            minIf(first_event_timestamp, first_event_timestamp != '1970-01-01 00:00:00') as start_time,
            MAX(last_event_timestamp) as end_time,
            SUM(click_count) as click_count,
            SUM(keypress_count) as keypress_count,
            groupArrayArray(urls) as urls,
            dateDiff('second', start_time, end_time) as duration,
            any(distinct_id) as distinct_id,
            SUM(has_full_snapshot) as full_snapshots
        FROM session_recording_events
        PREWHERE
            team_id = %(team_id)s
            {events_timestamp_clause}
        GROUP BY session_id
        HAVING full_snapshots > 0
        {recording_start_time_clause}
        {duration_clause}
        {session_ids_clause}
    """

    _session_recordings_query_with_events: str = """
    SELECT
        session_recordings.session_id,
        any(session_recordings.start_time) as start_time,
        any(session_recordings.end_time) as end_time,
        any(session_recordings.click_count) as click_count,
        any(session_recordings.keypress_count) as keypress_count,
        any(session_recordings.urls) as urls,
        any(session_recordings.duration) as duration,
        any(session_recordings.distinct_id) as distinct_id
        {event_filter_aggregate_select_clause}
    FROM (
        {core_events_query}
    ) AS events
    JOIN (
        {core_recordings_query}
    ) AS session_recordings
    ON session_recordings.distinct_id = events.distinct_id
    {recording_person_query}
    WHERE
        {event_and_recording_match_comditions_clause}
        {prop_filter_clause}
        {person_id_clause}
    GROUP BY session_recordings.session_id
    HAVING 1 = 1
    {event_filter_aggregate_having_clause}
    ORDER BY start_time DESC
    LIMIT %(limit)s OFFSET %(offset)s
    """

    _session_recordings_query: str = """
    SELECT
        session_recordings.session_id,
        any(session_recordings.start_time) as start_time,
        any(session_recordings.end_time) as end_time,
        any(session_recordings.click_count) as click_count,
        any(session_recordings.keypress_count) as keypress_count,
        any(session_recordings.urls) as urls,
        any(session_recordings.duration) as duration,
        any(session_recordings.distinct_id) as distinct_id
    FROM (
        {core_recordings_query}
    ) AS session_recordings
    {recording_person_query}
    WHERE 1 = 1
        {prop_filter_clause}
        {person_id_clause}
    GROUP BY session_recordings.session_id
    ORDER BY start_time DESC
    LIMIT %(limit)s OFFSET %(offset)s
    """

    @property
    def limit(self):
        return self._filter.limit or self.SESSION_RECORDINGS_DEFAULT_LIMIT

    def _determine_should_join_distinct_ids(self) -> None:
        self._should_join_distinct_ids = True

    def _determine_should_join_persons(self) -> None:
        super()._determine_should_join_persons()

        if self._filter.person_uuid:
            self._should_join_distinct_ids = True
            self._should_join_persons = True
            return

    def _determine_should_join_events(self):
        return self._filter.entities and len(self._filter.entities) > 0

    @cached_property
    def _get_properties_select_clause(self) -> str:
        clause = (
            f", events.elements_chain as elements_chain"
            if self._column_optimizer.should_query_elements_chain_column
            else ""
        )
        clause += " ".join(
            f", events.{column_name} as {column_name}" for column_name in self._column_optimizer.event_columns_to_query
        )
        return clause

    @cached_property
    def _get_person_id_clause(self) -> Tuple[str, Dict[str, Any]]:
        person_id_clause = ""
        person_id_params = {}
        if self._filter.person_uuid:
            person_id_clause = "AND person.id = %(person_uuid)s"
            person_id_params = {"person_uuid": self._filter.person_uuid}
        return person_id_clause, person_id_params

    # We want to select events beyond the range of the recording to handle the case where
    # a recording spans the time boundaries
    @cached_property
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

    @cached_property
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

    @cached_property
    def _get_filter_by_provided_session_ids_clause(self) -> Tuple[str, Dict[str, Any]]:
        if self._filter.session_ids is None:
            return "", {}

        return "AND session_id in %(session_ids)s", {"session_ids": self._filter.session_ids}

    @cached_property
    def _get_duration_clause(self) -> Tuple[str, Dict[str, Any]]:
        duration_clause = ""
        duration_params = {}
        if self._filter.recording_duration_filter:
            if self._filter.recording_duration_filter.operator == "gt":
                operator = ">"
            else:
                operator = "<"
            duration_clause = "\nAND duration {operator} %(recording_duration)s".format(operator=operator)
            duration_params = {"recording_duration": self._filter.recording_duration_filter.value}
        return duration_clause, duration_params

    def _get_recording_person_query(self) -> Tuple[str, Dict]:
        person_query, person_query_params = self._get_person_query()
        person_distinct_id_query = get_team_distinct_ids_query(self._team_id)
        if person_query:
            return (
                f"""
                    JOIN (
                    {person_distinct_id_query}
                    ) as pdi
                    ON pdi.distinct_id = session_recordings.distinct_id
                    {person_query}
                """,
                person_query_params,
            )
        return person_query, person_query_params

    def format_event_filter(self, entity: Entity, prepend: str, team_id: int) -> Tuple[str, Dict[str, Any]]:
        filter_sql, params = format_entity_filter(
            team_id=team_id,
            entity=entity,
            prepend=prepend,
            filter_by_team=False,
            person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id",
            hogql_context=self._filter.hogql_context,
        )

        filters, filter_params = parse_prop_grouped_clauses(
            team_id=team_id,
            property_group=entity.property_groups,
            prepend=prepend,
            allow_denormalized_props=True,
            has_person_id_joined=True,
            person_properties_mode=PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            hogql_context=self._filter.hogql_context,
        )
        filter_sql += f" {filters}"
        params = {**params, **filter_params}

        return filter_sql, params

    @cached_property
    def format_event_filters(self) -> EventFiltersSQL:
        non_aggregate_select_condition_clause = ""
        aggregate_event_select_clause = ""
        aggregate_select_clause = ""
        aggregate_having_clause = ""
        where_conditions = "AND event IN %(event_names)s"
        # Always include $pageview events so the start_url and end_url can be extracted
        event_names_to_filter: List[Union[int, str]] = []

        params: Dict = {}

        for index, entity in enumerate(self._filter.entities):
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                action = entity.get_action()
                event_names_to_filter.extend([ae for ae in action.get_step_events() if ae not in event_names_to_filter])
            else:
                if entity.id not in event_names_to_filter and entity.id is not None:
                    event_names_to_filter.append(entity.id)

            condition_sql, filter_params = self.format_event_filter(
                entity, prepend=f"event_matcher_{index}", team_id=self._team_id
            )
            aggregate_select_clause += f"""
            , countIf({condition_sql}) as count_event_match_{index}
            , groupUniqArrayIf(100)((events.timestamp, events.uuid, events.session_id, events.window_id), {condition_sql}) as matching_events_{index}
            """
            aggregate_having_clause += f"\nAND count_event_match_{index} > 0"
            params = {**params, **filter_params}

        params = {**params, "event_names": list(event_names_to_filter)}

        if len(event_names_to_filter) == 0:
            # using "All events"
            where_conditions = ""

        return EventFiltersSQL(
            non_aggregate_select_condition_clause,
            aggregate_event_select_clause,
            aggregate_select_clause,
            aggregate_having_clause,
            where_conditions,
            params,
        )

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        offset = self._filter.offset or 0
        base_params = {"team_id": self._team_id, "limit": self.limit + 1, "offset": offset}
        recording_person_query, recording_person_query_params = self._get_recording_person_query()

        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups,
            person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id",
        )

        events_timestamp_clause, events_timestamp_params = self._get_events_timestamp_clause
        recording_start_time_clause, recording_start_time_params = self._get_recording_start_time_clause
        session_ids_clause, session_ids_params = self._get_filter_by_provided_session_ids_clause
        person_id_clause, person_id_params = self._get_person_id_clause
        duration_clause, duration_params = self._get_duration_clause

        core_recordings_query = self._core_session_recordings_query.format(
            recording_start_time_clause=recording_start_time_clause,
            duration_clause=duration_clause,
            events_timestamp_clause=events_timestamp_clause,
            session_ids_clause=session_ids_clause,
        )

        if not self._determine_should_join_events():
            return (
                self._session_recordings_query.format(
                    core_recordings_query=core_recordings_query,
                    recording_person_query=recording_person_query,
                    prop_filter_clause=prop_query,
                    person_id_clause=person_id_clause,
                ),
                {
                    **base_params,
                    **person_id_params,
                    **recording_person_query_params,
                    **prop_params,
                    **events_timestamp_params,
                    **duration_params,
                    **recording_start_time_params,
                    **session_ids_params,
                },
            )

        event_filters = self.format_event_filters

        core_events_query, core_events_query_params = self._get_core_events_query()

        return (
            self._session_recordings_query_with_events.format(
                event_filter_aggregate_select_clause=event_filters.aggregate_select_clause,
                core_events_query=core_events_query,
                core_recordings_query=core_recordings_query,
                recording_person_query=recording_person_query,
                event_and_recording_match_comditions_clause=self._event_and_recording_match_conditions_clause,
                prop_filter_clause=prop_query,
                person_id_clause=person_id_clause,
                event_filter_aggregate_having_clause=event_filters.aggregate_having_clause,
            ),
            {
                **base_params,
                **person_id_params,
                **recording_person_query_params,
                **prop_params,
                **events_timestamp_params,
                **duration_params,
                **recording_start_time_params,
                **event_filters.params,
                **session_ids_params,
                **core_events_query_params,
            },
        )

    def _get_core_events_query(self) -> Tuple[str, Dict[str, Any]]:
        params: Dict[str, Any] = {}
        event_filters = self.format_event_filters
        properties_select_clause = self._get_properties_select_clause
        events_timestamp_clause, events_timestamp_params = self._get_events_timestamp_clause

        core_events_query = self._core_events_query.format(
            properties_select_clause=properties_select_clause,
            event_filter_where_conditions=event_filters.where_conditions,
            events_timestamp_clause=events_timestamp_clause,
        )

        return core_events_query, {**params, **events_timestamp_params}

    def _paginate_results(self, session_recordings) -> SessionRecordingQueryResult:
        more_recordings_available = False
        if len(session_recordings) > self.limit:
            more_recordings_available = True
            session_recordings = session_recordings[0 : self.limit]
        return SessionRecordingQueryResult(session_recordings, more_recordings_available)

    def _data_to_return(self, results: List[Any]) -> List[Dict[str, Any]]:
        default_columns = [
            "session_id",
            "start_time",
            "end_time",
            "click_count",
            "keypress_count",
            "urls",
            "duration",
            "distinct_id",
        ]

        return [
            {
                **dict(zip(default_columns, row[: len(default_columns)])),
                "matching_events": [
                    {
                        "events": [
                            dict(zip(["timestamp", "uuid", "session_id", "window_id"], event)) for event in row[i + 1]
                        ]
                    }
                    for i in range(len(default_columns), len(row), 2)
                ],
            }
            for row in results
        ]

    def run(self, *args, **kwargs) -> SessionRecordingQueryResult:
        self._filter.hogql_context.person_on_events_mode = PersonOnEventsMode.DISABLED
        query, query_params = self.get_query()
        query_results = sync_execute(query, {**query_params, **self._filter.hogql_context.values})
        session_recordings = self._data_to_return(query_results)
        return self._paginate_results(session_recordings)


class SessionRecordingListV2(SessionRecordingList):

    _core_events_query = """
        SELECT
            uuid,
            distinct_id,
            event,
            team_id,
            timestamp,
            "$session_id" AS session_id,
            "$window_id" AS window_id
            {properties_select_clause}
            {non_aggregate_select_condition_clause}

        FROM events
        WHERE
            team_id = %(team_id)s
            {event_filter_where_conditions}
            {events_timestamp_clause}
            AND notEmpty(session_id)
    """

    _core_events_query_grouped = """
        SELECT
            session_id,
            distinct_id
            {aggregate_event_select_clause}
        FROM (
            {ungrouped_core_events_query}
        ) GROUP BY session_id, distinct_id
        HAVING 1 = 1
        {event_filter_aggregate_having_clause}
    """

    _session_recordings_query_with_events = """
        SELECT
            session_recordings.session_id,
            start_time,
            end_time,
            click_count,
            keypress_count,
            urls,
            duration,
            session_recordings.distinct_id as distinct_id
            {event_filter_aggregate_select_clause}
        FROM (
            {core_events_query}
        ) AS events
        JOIN (
            {core_recordings_query}
        ) AS session_recordings
        ON session_recordings.session_id = events.session_id
        {recording_person_query}
        WHERE
            session_recordings.distinct_id == events.distinct_id
            {prop_filter_clause}
            {person_id_clause}
        ORDER BY start_time DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """

    def _get_core_events_query(self) -> Tuple[str, Dict[str, Any]]:
        params: Dict[str, Any] = {}
        event_filters = self.format_event_filters
        properties_select_clause = self._get_properties_select_clause
        events_timestamp_clause, events_timestamp_params = self._get_events_timestamp_clause

        core_events_query = self._core_events_query.format(
            properties_select_clause=properties_select_clause,
            non_aggregate_select_condition_clause=event_filters.non_aggregate_select_condition_clause,
            event_filter_where_conditions=event_filters.where_conditions,
            events_timestamp_clause=events_timestamp_clause,
        )

        grouped_events_query = self._core_events_query_grouped.format(
            aggregate_event_select_clause=event_filters.aggregate_event_select_clause,
            ungrouped_core_events_query=core_events_query,
            event_filter_aggregate_having_clause=event_filters.aggregate_having_clause,
        )

        return grouped_events_query, {**params, **events_timestamp_params}

    @cached_property
    def format_event_filters(self) -> EventFiltersSQL:
        non_aggregate_select_condition_clause = ""
        aggregate_event_select_clause = ""
        aggregate_select_clause = ""
        aggregate_having_clause = ""
        where_conditions = "AND event IN %(event_names)s"
        # Always include $pageview events so the start_url and end_url can be extracted
        event_names_to_filter: List[Union[int, str]] = []

        params: Dict = {}

        for index, entity in enumerate(self._filter.entities):
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                action = entity.get_action()
                event_names_to_filter.extend([ae for ae in action.get_step_events() if ae not in event_names_to_filter])
            else:
                if entity.id not in event_names_to_filter and entity.id is not None:
                    event_names_to_filter.append(entity.id)

            condition_sql, filter_params = self.format_event_filter(
                entity, prepend=f"event_matcher_{index}", team_id=self._team_id
            )
            aggregate_event_select_clause += f"""
            , groupUniqArrayIf(100)((timestamp, uuid, session_id, window_id), event_match_{index} = 1) AS matching_events_{index}
            , sum(event_match_{index}) AS matches_{index}
            """

            aggregate_select_clause += f"""
            , matches_{index}
            , matching_events_{index}
            """

            non_aggregate_select_condition_clause += f"""
            , if({condition_sql}, 1, 0) as event_match_{index}
            """
            aggregate_having_clause += f"\nAND matches_{index} > 0"
            params = {**params, **filter_params}

        params = {**params, "event_names": list(event_names_to_filter)}

        if len(event_names_to_filter) == 0:
            # using "All events"
            where_conditions = ""

        return EventFiltersSQL(
            non_aggregate_select_condition_clause,
            aggregate_event_select_clause,
            aggregate_select_clause,
            aggregate_having_clause,
            where_conditions,
            params,
        )
