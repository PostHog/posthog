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
    where_conditions: str
    params: Dict[str, Any]


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

    _persons_lookup_cte = """
    distinct_ids_for_person as (
        SELECT distinct_id, argMax(person_id, version) as person_id
        FROM person_distinct_id2 as pdi
            {filter_persons_clause}
        PREWHERE team_id = %(team_id)s
        GROUP BY distinct_id
        HAVING
            argMax(is_deleted, version) = 0
            {filter_by_person_uuid_condition}
            {filter_by_cohort_condition}
    )
    """

    _session_recordings_base_query: str = """
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
       {event_ids_selector}
    FROM session_replay_events s
    {events_join_clause}
    PREWHERE s.team_id = %(team_id)s
        -- regardless of what other filters are applied
        -- limit by storage TTL
        AND s.min_first_timestamp >= %(clamped_to_storage_ttl)s
         -- we can filter on the pre-aggregated timestamp columns
        -- because any not-the-lowest min value is _more_ greater than the min value
        -- and any not-the-highest max value is _less_ lower than the max value
        AND s.min_first_timestamp >= %(start_time)s
        AND s.max_last_timestamp <= %(end_time)s
    """

    _session_recordings_query: str = """
        {person_cte}
        {session_recordings_base_query}
        -- these condition are in the prewhere from the base query
        -- may need to match fixed session ids from the query filter
        {session_ids_clause}
        -- person cte is matched in a where clause
        WHERE 1=1 {person_cte_match_clause}
    GROUP BY session_id
        HAVING 1=1 {duration_clause} {console_log_clause}
    ORDER BY start_time DESC
    LIMIT %(limit)s OFFSET %(offset)s
        """

    _session_recordings_query_with_events = """
        -- person_cte is optional,
        -- it adds the comma needed to have multiple CTEs if it is present
        WITH {person_cte}
        events_session_ids AS (
            SELECT
                groupUniqArray(event) as event_names,
                groupArray(uuid) as event_ids,
                `$session_id` as session_id
            FROM events
            PREWHERE
                team_id = %(team_id)s
                {events_timestamp_clause}
                and notEmpty(session_id)
                WHERE 1=1 {event_filter_where_conditions}
            GROUP BY session_id
            {event_filter_having_events_condition}
        )
        {session_recordings_base_query}
        -- these condition are in the prewhere from the base query
        -- may need to match fixed session ids from the query filter
        {session_ids_clause}
        -- person cte is matched in a where clause
        WHERE 1=1 {person_cte_match_clause}
        GROUP BY session_id
        HAVING 1=1 {duration_clause} {console_log_clause}
        ORDER BY start_time DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """

    @cached_property
    def build_event_filters(self) -> SummaryEventFiltersSQL:
        condition_sql = ""

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
            condition_sql += f"{joining} ({this_entity_condition_sql})"
            params = {**params, **this_entity_filter_params}

        params = {**params, "event_names": list(event_names_to_filter)}

        if len(event_names_to_filter) == 0:
            # using "All events"
            having_conditions = ""
        else:
            having_conditions = "HAVING hasAll(event_names, %(event_names)s)"

        return SummaryEventFiltersSQL(
            having_conditions=having_conditions,
            where_conditions=f"AND {condition_sql}" if condition_sql else "",
            params=params,
        )

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
            "matching_events",
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

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        offset = self._filter.offset or 0

        base_params = {
            "team_id": self._team_id,
            "limit": self.limit + 1,
            "offset": offset,
            "clamped_to_storage_ttl": (datetime.datetime.now() - datetime.timedelta(days=self.ttl_days)),
        }

        recording_person_query, recording_person_query_params = self._get_recording_person_query()

        event_filters = self.build_event_filters
        events_timestamp_clause, events_timestamp_params = self._get_events_timestamp_clause
        _, recording_start_time_params = self._get_recording_start_time_clause
        session_ids_clause, session_ids_params = self.session_ids_clause
        person_id_clause, person_id_params = self._get_person_id_clause
        duration_clause, duration_params = self.duration_clause(self._filter.duration_type_filter)

        person_cte, person_cte_match_clause, person_person_cte_params = self._persons_cte_clause

        console_log_clause = self._get_console_log_clause(self._filter.console_logs_filter)

        if not self._determine_should_join_events():
            return (
                self._session_recordings_query.format(
                    person_id_clause=person_id_clause,
                    duration_clause=duration_clause,
                    person_cte=f"with {person_cte}" if person_cte else "",
                    person_cte_match_clause=person_cte_match_clause,
                    session_ids_clause=session_ids_clause,
                    session_recordings_base_query=self._session_recordings_base_query.format(
                        event_ids_selector="",
                        events_join_clause="",
                    ),
                    console_log_clause=console_log_clause,
                ),
                {
                    **base_params,
                    **recording_start_time_params,
                    **person_id_params,
                    **duration_params,
                    **person_person_cte_params,
                    **session_ids_params,
                },
            )

        return (
            self._session_recordings_query_with_events.format(
                person_id_clause=person_id_clause,
                event_filter_where_conditions=event_filters.where_conditions,
                event_filter_having_events_condition=event_filters.having_conditions,
                events_timestamp_clause=events_timestamp_clause,
                duration_clause=duration_clause,
                person_cte=f"{person_cte}," if person_cte else "",
                person_cte_match_clause=person_cte_match_clause,
                session_ids_clause=session_ids_clause,
                session_recordings_base_query=self._session_recordings_base_query.format(
                    event_ids_selector=",any(e.event_ids) as matching_events",
                    events_join_clause="JOIN events_session_ids e ON s.session_id = e.session_id",
                ),
                console_log_clause=console_log_clause,
            ),
            {
                **base_params,
                **person_id_params,
                **recording_person_query_params,
                **events_timestamp_params,
                **duration_params,
                **recording_start_time_params,
                **event_filters.params,
                **person_person_cte_params,
                **session_ids_params,
            },
        )

    @cached_property
    def _persons_cte_clause(self) -> Tuple[str, str, Dict[str, Any]]:
        person_cte_match_clause = ""
        person_cte = ""
        person_id_params: Dict[str, Any] = {}

        person_query, person_query_params = self._get_person_query()

        # KLUDGE: it is possible coincidence since recordings have their own filter component
        # but this prop_query is only used when filtering by cohort membership
        # since we haven't joined replays to person table this condition is only used for and
        # needs adding to the person CTE
        # in the two versions of the session_recording_list this is a "top-level" condition
        # because they do join the tables
        cohort_filter_condition, cohort_filter_params = self._get_prop_groups(
            self._filter.property_groups, person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id"
        )

        if self._filter.person_uuid or person_query:
            person_id_params = {
                **person_id_params,
                **person_query_params,
                "person_uuid": self._filter.person_uuid,
                **cohort_filter_params,
            }
            filter_persons_clause = person_query or ""
            filter_by_person_uuid_condition = "and person_id = %(person_uuid)s" if self._filter.person_uuid else ""

            person_cte = self._persons_lookup_cte.format(
                filter_persons_clause=filter_persons_clause,
                filter_by_person_uuid_condition=filter_by_person_uuid_condition,
                filter_by_cohort_condition=cohort_filter_condition,
            )

            person_cte_match_clause = "AND distinct_id in (select distinct_id from distinct_ids_for_person)"
        return person_cte, person_cte_match_clause, person_id_params

    @cached_property
    def _get_person_id_clause(self) -> Tuple[str, Dict[str, Any]]:
        person_id_clause = ""
        person_id_params = {}
        if self._filter.person_uuid:
            person_id_clause = "AND person_id = %(person_uuid)s"
            person_id_params = {"person_uuid": self._filter.person_uuid}
        return person_id_clause, person_id_params

    def _get_recording_person_query(self) -> Tuple[str, Dict]:
        # not used in this version of a session_recording_list
        return "", {}

    def _get_console_log_clause(self, console_logs_filter: List[Literal["error", "warn", "log"]]) -> str:
        filters = [f"console_{log}_count > 0" for log in console_logs_filter]
        return f"AND ({' OR '.join(filters)})" if filters else ""
