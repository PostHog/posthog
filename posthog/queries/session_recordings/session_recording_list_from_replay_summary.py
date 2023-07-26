import dataclasses
import datetime
from typing import Any, Dict, List, Tuple, Union, Literal

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.instance_setting import get_instance_setting
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList


@dataclasses.dataclass(frozen=True)
class SummaryEventFiltersSQL:
    having_conditions: str
    having_select: str
    where_conditions: str
    params: Dict[str, Any]


class PersonsQuery(SessionRecordingList):
    _raw_persons_query = """
        SELECT distinct_id, argMax(person_id, version) as person_id
        {select_person_props}
        FROM person_distinct_id2 as pdi
            {filter_persons_clause}
        WHERE team_id = %(team_id)s
        {prop_filter_clause}
        GROUP BY distinct_id
        HAVING
            argMax(is_deleted, version) = 0
            {filter_by_person_uuid_condition}
    """

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups, person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id"
        )

        person_query, person_query_params = self._get_person_query()
        should_join_persons = self._filter.person_uuid or person_query

        if not should_join_persons:
            return "", {}
        else:
            filter_persons_clause = person_query or ""
            filter_by_person_uuid_condition = "and person_id = %(person_uuid)s" if self._filter.person_uuid else ""
            return self._raw_persons_query.format(
                filter_persons_clause=filter_persons_clause,
                select_person_props=", argMax(person_props, version) as person_props"
                if "person_props" in filter_persons_clause
                else "",
                prop_filter_clause=prop_query,
                filter_by_person_uuid_condition=filter_by_person_uuid_condition,
            ), {
                "team_id": self._team_id,
                **person_query_params,
                "person_uuid": self._filter.person_uuid,
                **prop_params,
            }


class SessionIdEventsQuery(SessionRecordingList):
    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(
            **kwargs,
        )
        self.ttl_days = (get_instance_setting("RECORDINGS_TTL_WEEKS") or 3) * 7

    _raw_events_query = """
        SELECT
            {event_filter_having_events_select}
            `$session_id`
        FROM events e
        {persons_join}
        PREWHERE
            team_id = %(team_id)s
            -- regardless of what other filters are applied
            -- limit by storage TTL
            AND e.timestamp >= %(clamped_to_storage_ttl)s
            AND e.timestamp <= now()
        WHERE
            notEmpty(`$session_id`)
            {events_timestamp_clause}
            {event_filter_where_conditions}
            {prop_filter_clause}
            {provided_session_ids_clause}
        GROUP BY `$session_id`
        HAVING 1=1 {event_filter_having_events_condition}
    """

    @cached_property
    def build_event_filters(self) -> SummaryEventFiltersSQL:
        event_names_to_filter: List[Union[int, str]] = []
        params: Dict = {}
        condition_sql = ""

        for index, entity in enumerate(self._filter.entities):
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                action = entity.get_action()
                event_names_to_filter.extend([ae for ae in action.get_step_events() if ae not in event_names_to_filter])
            else:
                if entity.id and entity.id not in event_names_to_filter:
                    event_names_to_filter.append(entity.id)

            this_entity_condition_sql, this_entity_filter_params = self.format_event_filter(
                entity, prepend=f"event_matcher_{index}", team_id=self._team_id
            )
            joining = "OR" if index > 0 else ""
            condition_sql += f"{joining} {this_entity_condition_sql}"
            # wrap in smooths to constrain the scope of the OR
            condition_sql = f"( {condition_sql} )"
            params = {**params, **this_entity_filter_params}

        params = {**params, "event_names": list(event_names_to_filter)}

        if len(event_names_to_filter) == 0:
            # using "All events"
            having_conditions = ""
            having_select = ""
        else:
            having_conditions = "AND hasAll(event_names, %(event_names)s)"
            having_select = """
                -- select the unique events in this session to support filtering sessions by presence of an event
                    groupUniqArray(event) as event_names,"""

        return SummaryEventFiltersSQL(
            having_conditions=having_conditions,
            having_select=having_select,
            where_conditions=f"AND {condition_sql}" if condition_sql else "",
            params=params,
        )

    @cached_property
    def _get_filter_by_provided_session_ids_clause(self) -> Tuple[str, Dict[str, Any]]:
        if self._filter.session_ids is None:
            return "", {}

        return "AND `$session_id` in %(session_ids)s", {"session_ids": self._filter.session_ids}

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        if not self._determine_should_join_events():
            return "", {}

        base_params = {
            "team_id": self._team_id,
            "clamped_to_storage_ttl": (datetime.datetime.now() - datetime.timedelta(days=self.ttl_days)),
        }

        _, recording_start_time_params = self._get_recording_start_time_clause
        provided_session_ids_clause, provided_session_ids_params = self._get_filter_by_provided_session_ids_clause

        event_filters = self.build_event_filters
        event_filters_params = event_filters.params
        events_timestamp_clause, events_timestamp_params = self._get_events_timestamp_clause

        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups, person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id"
        )

        persons_select, persons_join_params = PersonsQuery(filter=self._filter, team=self._team).get_query()
        if persons_select:
            persons_select = f"JOIN ({persons_select}) as pdi on pdi.distinct_id = e.distinct_id"

        return (
            self._raw_events_query.format(
                event_filter_where_conditions=event_filters.where_conditions,
                event_filter_having_events_condition=event_filters.having_conditions,
                event_filter_having_events_select=event_filters.having_select,
                events_timestamp_clause=events_timestamp_clause,
                prop_filter_clause=prop_query,
                provided_session_ids_clause=provided_session_ids_clause,
                persons_join=persons_select,
            ),
            {
                **base_params,
                **recording_start_time_params,
                **provided_session_ids_params,
                **events_timestamp_params,
                **event_filters_params,
                **prop_params,
                **persons_join_params,
            },
        )

    @cached_property
    def _get_person_id_clause(self) -> Tuple[str, Dict[str, Any]]:
        person_id_clause = ""
        person_id_params = {}
        if self._filter.person_uuid:
            person_id_clause = "AND person_id = %(person_uuid)s"
            person_id_params = {"person_uuid": self._filter.person_uuid}
        return person_id_clause, person_id_params


class SessionRecordingListFromReplaySummary(SessionRecordingList):
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(
            **kwargs,
        )
        self.ttl_days = (get_instance_setting("RECORDINGS_TTL_WEEKS") or 3) * 7

    _session_recordings_query: str = """
    SELECT
       s.session_id,
       any(s.team_id),
       any(s.distinct_id),
       min(s.min_first_timestamp) as start_time,
       max(s.max_last_timestamp) as end_time,
       dateDiff('SECOND', start_time, end_time) as duration,
       argMinMerge(s.first_url) as first_url,
       sum(s.click_count),
       sum(s.keypress_count),
       sum(s.mouse_activity_count),
       sum(s.active_milliseconds)/1000 as active_seconds,
       duration-active_seconds as inactive_seconds,
       sum(s.console_log_count) as console_log_count,
       sum(s.console_warn_count) as console_warn_count,
       sum(s.console_error_count) as console_error_count
    FROM session_replay_events s
    WHERE s.team_id = %(team_id)s
        -- regardless of what other filters are applied
        -- limit by storage TTL
        AND s.min_first_timestamp >= %(clamped_to_storage_ttl)s
         -- we can filter on the pre-aggregated timestamp columns
        -- because any not-the-lowest min value is _more_ greater than the min value
        -- and any not-the-highest max value is _less_ lower than the max value
        AND s.min_first_timestamp >= %(start_time)s
        AND s.max_last_timestamp <= %(end_time)s
        {persons_sub_query}
        {events_sub_query}
    {provided_session_ids_clause}
    GROUP BY session_id
        HAVING 1=1 {duration_clause} {console_log_clause}
    ORDER BY start_time DESC
    LIMIT %(limit)s OFFSET %(offset)s
    """

    def _data_to_return(self, results: List[Any]) -> List[Dict[str, Any]]:
        default_columns = [
            "session_id",
            "team_id",
            "distinct_id",
            "start_time",
            "end_time",
            "duration",
            "first_url",
            "click_count",
            "keypress_count",
            "mouse_activity_count",
            "active_seconds",
            "inactive_seconds",
            "console_log_count",
            "console_warn_count",
            "console_error_count",
        ]

        return [
            {
                **dict(zip(default_columns, row[: len(default_columns)])),
            }
            for row in results
        ]

    @property
    def limit(self):
        return self._filter.limit or self.SESSION_RECORDINGS_DEFAULT_LIMIT

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        offset = self._filter.offset or 0

        base_params = {
            "team_id": self._team_id,
            "limit": self.limit + 1,
            "offset": offset,
            "clamped_to_storage_ttl": (datetime.datetime.now() - datetime.timedelta(days=self.ttl_days)),
        }

        _, recording_start_time_params = self._get_recording_start_time_clause
        provided_session_ids_clause, provided_session_ids_params = self._get_filter_by_provided_session_ids_clause
        duration_clause, duration_params = self.duration_clause(self._filter.duration_type_filter)
        console_log_clause = self._get_console_log_clause(self._filter.console_logs_filter)

        events_select, events_join_params = SessionIdEventsQuery(
            team=self._team,
            filter=self._filter,
        ).get_query()
        if events_select:
            events_select = f"AND s.session_id in (select `$session_id` as session_id from ({events_select}) as session_events_sub_query)"

        persons_select, persons_select_params = PersonsQuery(filter=self._filter, team=self._team).get_query()
        if persons_select:
            persons_select = (
                f"AND s.distinct_id in (select distinct_id from ({persons_select}) as session_persons_sub_query)"
            )

        return (
            self._session_recordings_query.format(
                duration_clause=duration_clause,
                provided_session_ids_clause=provided_session_ids_clause,
                console_log_clause=console_log_clause,
                persons_sub_query=persons_select,
                events_sub_query=events_select,
            ),
            {
                **base_params,
                **events_join_params,
                **recording_start_time_params,
                **duration_params,
                **provided_session_ids_params,
                **persons_select_params,
            },
        )

    def duration_clause(
        self, duration_filter_type: Literal["duration", "active_seconds", "inactive_seconds"]
    ) -> Tuple[str, Dict[str, Any]]:
        duration_clause = ""
        duration_params = {}
        if self._filter.recording_duration_filter:
            if self._filter.recording_duration_filter.operator == "gt":
                operator = ">"
            else:
                operator = "<"
            duration_clause = "\nAND {duration_type} {operator} %(recording_duration)s".format(
                duration_type=duration_filter_type, operator=operator
            )
            duration_params = {
                "recording_duration": self._filter.recording_duration_filter.value,
            }
        return duration_clause, duration_params

    @staticmethod
    def _get_console_log_clause(console_logs_filter: List[Literal["error", "warn", "log"]]) -> str:
        filters = [f"console_{log}_count > 0" for log in console_logs_filter]
        return f"AND ({' OR '.join(filters)})" if filters else ""
