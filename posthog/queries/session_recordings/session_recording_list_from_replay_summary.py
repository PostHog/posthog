import dataclasses
from typing import Any, Dict, List, Tuple, Union

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList, EventFiltersSQL


@dataclasses.dataclass(frozen=True)
class SummaryEventFiltersSQL(EventFiltersSQL):
    simple_event_matching_select_condition_clause: str
    non_aggregate_select_condition_summing_clause: str


class SessionRecordingListFromReplaySummary(SessionRecordingList):
    # no longer need to return matching events or segments
    # so based on the filter we can find session ids for the matched events
    # then load sessions for those ids from the replay table
    # The SessionRecordingList interface is to have a run method
    # run implicitly calls get_query
    # and returns SessionRecordingQueryResult
    # because it doesn't return MatchingEvents any person/event selection templating is redundant here
    # assume this is so fast we don't have to page 🤘

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

    _session_recordings_query: str = """
        {person_cte}
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
        {person_cte_match_clause}
        -- may also need to match session ids from the query filter
        {session_ids_clause}
    GROUP BY session_id
        HAVING start_time >= %(start_time)s
        AND end_time <= %(end_time)s
        {duration_clause}
    ORDER BY start_time DESC
        """

    _session_recordings_query_with_events = """
        -- person_cte is optional,
        -- it adds the comma needed to have multiple CTEs if it is present
        with {person_cte}
        events_session_ids AS (
        -- this core query has to select the session_ids from the events table
        -- because the non_aggregate_select_condition_clause is used to AND conditions together
        -- but, we want to select a simple set of session ids
        -- we have to group by session_id and sum any matching columns
        SELECT session_id {non_aggregate_select_condition_summing_clause}
         FROM
            (SELECT
                `$session_id` as session_id
                {non_aggregate_select_condition_clause}
            FROM events
            PREWHERE
                team_id = %(team_id)s
                {events_timestamp_clause}
                {event_filter_where_conditions}
                and notEmpty(session_id)) AS inner_event_q
        GROUP BY session_id
        HAVING 1=1 {event_matches_filter_conditions}
        )
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
        {person_cte_match_clause}
        -- matches session ids from events CTE
        AND session_id in (select session_id from events_session_ids)
        -- may also need to match session ids from the query filter
        {session_ids_clause}
        GROUP BY session_id
        HAVING start_time >= %(start_time)s
        AND end_time <= %(end_time)s
        {duration_clause}
        ORDER BY start_time DESC
        """

    @cached_property
    def format_event_filters(self) -> SummaryEventFiltersSQL:
        simple_event_matching_select_condition_clause = ""
        non_aggregate_select_condition_clause = ""
        non_aggregate_select_condition_summing_clause = ""
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
                if entity.id and entity.id not in event_names_to_filter:
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

            simple_event_matching_select_condition_clause += f"""
                        , if({condition_sql}, 1, 0) as matches_{index}
                        """

            non_aggregate_select_condition_summing_clause += f"""
                                    , sum(matches_{index}) as matches_{index}
                                    """

            aggregate_having_clause += f"\nAND matches_{index} > 0"
            params = {**params, **filter_params}

        params = {**params, "event_names": list(event_names_to_filter)}

        if len(event_names_to_filter) == 0:
            # using "All events"
            where_conditions = ""

        return SummaryEventFiltersSQL(
            simple_event_matching_select_condition_clause=simple_event_matching_select_condition_clause,
            non_aggregate_select_condition_clause=non_aggregate_select_condition_clause,
            non_aggregate_select_condition_summing_clause=non_aggregate_select_condition_summing_clause,
            aggregate_event_select_clause=aggregate_event_select_clause,
            aggregate_select_clause=aggregate_select_clause,
            aggregate_having_clause=aggregate_having_clause,
            where_conditions=where_conditions,
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

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        # offset = self._filter.offset or 0
        base_params = {
            "team_id": self._team_id,
            # "limit": self.limit + 1,
            # "offset": offset
        }
        recording_person_query, recording_person_query_params = self._get_recording_person_query()

        event_filters = self.format_event_filters
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

        to_be_debugged = (
            self._session_recordings_query_with_events.format(
                person_id_clause=person_id_clause,
                event_filter_where_conditions=event_filters.where_conditions,
                events_timestamp_clause=events_timestamp_clause,
                non_aggregate_select_condition_clause=event_filters.simple_event_matching_select_condition_clause,
                event_matches_filter_conditions=event_filters.aggregate_having_clause,
                non_aggregate_select_condition_summing_clause=event_filters.non_aggregate_select_condition_summing_clause,
                duration_clause=duration_clause,
                person_cte=f"{person_cte}," if person_cte else "",
                person_cte_match_clause=person_cte_match_clause,
                session_ids_clause=session_ids_clause,
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
        # breakpoint()
        return to_be_debugged

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
