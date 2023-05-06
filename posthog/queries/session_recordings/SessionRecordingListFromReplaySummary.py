from typing import Any, Dict, List, Tuple, Union

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList, EventFiltersSQL


class SessionRecordingListFromReplaySummary(SessionRecordingList):
    # no longer need to return matching events or segments
    # so based on the filter we can find session ids for the matched events
    # then load sessions for those ids from the replay table
    # The SessionRecordingList interface is to have a run method
    # run implicitly calls get_query
    # and returns SessionRecordingQueryResult
    # because it doesn't return MatchingEvents any person/event selection templating is redundant here
    # assume this is so fast we don't have to page 🤘

    _core_events_query = """
        SELECT
            `$session_id` as session_id
        FROM events
        PREWHERE
            team_id = %(team_id)s
            {events_timestamp_clause}
            {event_filter_where_conditions}
            {prop_filter_clause}
            {person_id_clause}
            and notEmpty(session_id)
    """

    _session_recordings_query_base = """
        select
       session_id,
       any(team_id),
       any(distinct_id),
       min(first_timestamp) as start_time,
       max(last_timestamp) as end_time,
       dateDiff('SECOND', min(first_timestamp), max(last_timestamp)) as duration,
       sum(click_count),
       sum(keypress_count),
       sum(mouse_activity_count),
       round((sum(active_milliseconds)/1000)/duration, 2) as active_time
    from session_replay_events
    prewhere team_id = %(team_id)s
    and first_timestamp >= %(start_time)s
    and last_timestamp <= %(end_time)s
    """

    _session_recordings_query: str = (
        _session_recordings_query_base
        + """
    group by session_id
    ORDER BY start_time DESC
        """
    )

    _session_recordings_query_with_events = f"""
        with events_session_ids as (
        {_core_events_query}
        )
        {_session_recordings_query_base}
        and session_id in (select session_id from events_session_ids)
        group by session_id
        ORDER BY start_time DESC
        """

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

        # each entity condition needs to be added to the event query.
        # so it would end up for two entities as
        # WHERE AND event IN %(event_names)s
        # and ((condition_sql1) OR (condition_sql2))
        where_conditions_for_entities: List[str] = []

        for index, entity in enumerate(self._filter.entities):
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                action = entity.get_action()
                event_names_to_filter.extend([ae for ae in action.get_step_events() if ae not in event_names_to_filter])
            else:
                if entity.id not in event_names_to_filter:
                    event_names_to_filter.append(entity.id)

            condition_sql, filter_params = self.format_event_filter(
                entity, prepend=f"event_matcher_{index}", team_id=self._team_id
            )

            where_conditions_for_entities.append(condition_sql)

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

        if where_conditions_for_entities:
            where_conditions += f"\nAND ({' OR '.join(where_conditions_for_entities)})"

        params = {**params, "event_names": list(event_names_to_filter)}

        return EventFiltersSQL(
            non_aggregate_select_condition_clause,
            aggregate_event_select_clause,
            aggregate_select_clause,
            aggregate_having_clause,
            where_conditions,
            params,
        )

    def _data_to_return(self, results: List[Any]) -> List[Dict[str, Any]]:
        default_columns = [
            "session_id",
            "team_id",
            "distinct_id",
            "start_time",
            "end_time",
            "duration",
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

        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups, person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id"
        )

        event_filters = self.format_event_filters
        events_timestamp_clause, events_timestamp_params = self._get_events_timestamp_clause
        _, recording_start_time_params = self._get_recording_start_time_clause
        session_ids_clause, session_ids_params = self.session_ids_clause
        person_id_clause, person_id_params = self._get_person_id_clause
        duration_clause, duration_params = self._get_duration_clause

        if not self._determine_should_join_events():
            return (
                self._session_recordings_query.format(
                    # recording_person_query=recording_person_query,
                    # prop_filter_clause=prop_query,
                    # person_id_clause=person_id_clause,
                ),
                {
                    **base_params,
                    **recording_start_time_params,
                    # **person_id_params,
                    # **recording_person_query_params,
                    # **prop_params,
                    # **events_timestamp_params,
                    # **duration_params,
                },
            )

        to_be_debugged = (
            self._session_recordings_query_with_events.format(
                # recording_person_query=recording_person_query,
                prop_filter_clause=prop_query,
                person_id_clause=person_id_clause,
                event_filter_where_conditions=event_filters.where_conditions,
                events_timestamp_clause=events_timestamp_clause,
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
            },
        )
        # breakpoint()
        return to_be_debugged
