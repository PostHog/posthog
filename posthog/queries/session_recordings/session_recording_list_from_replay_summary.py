import dataclasses
from typing import Any, Dict, List, Tuple, Union

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList


@dataclasses.dataclass(frozen=True)
class SummaryEventFiltersSQL:
    where_conditions: str
    params: Dict[str, Any]


class SessionRecordingListFromReplaySummary(SessionRecordingList):
    # no longer need to return matching events or segments
    # so based on the filter we can find session ids for the matched events
    # then load sessions for those ids from the replay table
    # The SessionRecordingList interface is to have a run method
    # run implicitly calls get_query
    # and returns SessionRecordingQueryResult
    # because it doesn't return MatchingEvents any person/event selection templating is redundant here

    SESSION_RECORDINGS_DEFAULT_LIMIT = 50

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
       session_id,
       any(team_id),
       any(distinct_id),
       min(min_first_timestamp) as start_time,
       max(max_last_timestamp) as end_time,
       dateDiff('SECOND', start_time, end_time) as duration,
       argMinMerge(first_url) as first_url,
       sum(click_count),
       sum(keypress_count),
       sum(mouse_activity_count),
       round((sum(active_milliseconds)/1000)/duration, 2) as active_time
    FROM session_replay_events
    PREWHERE team_id = %(team_id)s
         -- we can filter on the pre-aggregated timestamp columns
        -- because any not-the-lowest min value is _more_ greater than the min value
        -- and any not-the-highest max value is _less_ lower than the max value
        AND min_first_timestamp >= %(start_time)s
        AND max_last_timestamp <= %(end_time)s
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
        HAVING 1=1 {duration_clause}
    ORDER BY start_time DESC
    LIMIT %(limit)s OFFSET %(offset)s
        """

    _session_recordings_query_with_events = """
        -- person_cte is optional,
        -- it adds the comma needed to have multiple CTEs if it is present
        WITH {person_cte}
        events_session_ids AS (
            SELECT
                distinct `$session_id` as session_id
            FROM events
            PREWHERE
                team_id = %(team_id)s
                {events_timestamp_clause}
                and notEmpty(session_id)
                WHERE 1=1 {event_filter_where_conditions}
        )
        {session_recordings_base_query}
        -- these condition are in the prewhere from the base query
        -- matches session ids from events CTE
        AND session_id in (select session_id from events_session_ids)
        -- may need to match fixed session ids from the query filter
        {session_ids_clause}
        -- person cte is matched in a where clause
        WHERE 1=1 {person_cte_match_clause}
        GROUP BY session_id
        HAVING 1=1 {duration_clause}
        ORDER BY start_time DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """

    @cached_property
    def build_event_filters(self) -> SummaryEventFiltersSQL:
        condition_sql = ""
        where_conditions = "AND event IN %(event_names)s"
        event_names_to_filter: List[Union[int, str]] = []

        params: Dict = {}

        for index, entity in enumerate(self._filter.entities):
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                action = entity.get_action()
                event_names_to_filter.extend([ae for ae in action.get_step_events() if ae not in event_names_to_filter])
            else:
                if entity.id and entity.id not in event_names_to_filter:
                    event_names_to_filter.append(entity.id)

            condition_sql, filter_params = self.format_event_filter(
                entity, prepend=f"event_matcher_{index}", team_id=self._team_id
            )

            params = {**params, **filter_params}

        params = {**params, "event_names": list(event_names_to_filter)}

        if len(event_names_to_filter) == 0:
            # using "All events"
            where_conditions = ""

        return SummaryEventFiltersSQL(
            where_conditions=where_conditions + f"AND {condition_sql}" if condition_sql else "",
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
            "active_time",
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
        base_params = {"team_id": self._team_id, "limit": self.limit + 1, "offset": offset}

        recording_person_query, recording_person_query_params = self._get_recording_person_query()

        event_filters = self.build_event_filters
        events_timestamp_clause, events_timestamp_params = self._get_events_timestamp_clause
        _, recording_start_time_params = self._get_recording_start_time_clause
        session_ids_clause, session_ids_params = self.session_ids_clause
        person_id_clause, person_id_params = self._get_person_id_clause
        duration_clause, duration_params = self._get_duration_clause

        person_cte, person_cte_match_clause, person_person_cte_params = self._persons_cte_clause

        if not self._determine_should_join_events():
            return (
                self._session_recordings_query.format(
                    person_id_clause=person_id_clause,
                    duration_clause=duration_clause,
                    person_cte=f"with {person_cte}" if person_cte else "",
                    person_cte_match_clause=person_cte_match_clause,
                    session_ids_clause=session_ids_clause,
                    session_recordings_base_query=self._session_recordings_base_query,
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
                events_timestamp_clause=events_timestamp_clause,
                duration_clause=duration_clause,
                person_cte=f"{person_cte}," if person_cte else "",
                person_cte_match_clause=person_cte_match_clause,
                session_ids_clause=session_ids_clause,
                session_recordings_base_query=self._session_recordings_base_query,
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
