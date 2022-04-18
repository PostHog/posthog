from typing import Any, Dict, List, Optional, Set, Tuple, Union

from ee.clickhouse.materialized_columns.columns import ColumnName
from ee.clickhouse.models.cohort import get_count_operator, get_entity_query
from ee.clickhouse.queries.event_query import EnterpriseEventQuery
from posthog.models import Filter, Team
from posthog.models.action import Action
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.property import Property, PropertyGroup, PropertyName
from posthog.queries.column_optimizer import ColumnOptimizer

Relative_Date = Tuple[int, str]
NOW: Relative_Date = (0, "now")

Period = Tuple[Relative_Date, Relative_Date]
Event = Tuple[str, Tuple[str, int]]
Event_In_Period = Tuple[Event, Period]

USES_PERIOD = ["performed_event", "performed_event_muliple", "stopped_performing_event", "restarted_performing_event"]


class CohortOptimizer(ColumnOptimizer):
    _events = []

    @cached_property
    def dates_to_query_column_names(self) -> Dict[Relative_Date, Tuple[str, str]]:
        _dates = {NOW: "now"}
        for idx, prop in enumerate(self.filter.property_groups.flat):
            idx_label = idx * 2  # count by 2 because we can have up to 4 labels per step
            if prop.time_interval is not None and prop.time_value is not None:
                _dates[(prop.time_value, prop.time_interval)] = f"date_{idx_label}"
            if prop.seq_time_interval is not None and prop.seq_time_value is not None:
                _dates[(prop.seq_time_value, prop.seq_time_interval)] = f"date_{idx_label + 1}"
        return _dates

    def dates_to_query(self) -> List[Relative_Date]:
        return list(self.dates_to_query_column_names.keys())

    def get_date_column(self, period: Relative_Date) -> ColumnName:
        return self.dates_to_query_column_names[period]

    @cached_property
    def events_in_period_to_query_column_names(self) -> Dict[Event_In_Period, str]:
        _events = {}
        for idx, prop in enumerate(self.filter.property_groups.flat):
            idx_label = idx * 2  # count by 2 because we can have up to 4 labels per step
            if prop.type in USES_PERIOD:
                if (
                    prop.key is not None
                    and prop.event_type is not None
                    and prop.time_interval is not None
                    and prop.time_value is not None
                ):
                    _start_date = (prop.time_value, prop.time_interval)
                    _end_date = NOW
                    _period = (_start_date, _end_date)
                    _event = (prop.event_type, prop.key)
                    self.add_event_type(_event)
                    _events[
                        (_event, _period)
                    ] = f"event_{idx_label}_from_{self.get_date_column(_start_date)}_to_{self.get_date_column(NOW)}"
                if (
                    prop.seq_event is not None
                    and prop.seq_event_type is not None
                    and prop.seq_time_interval is not None
                    and prop.seq_time_value is not None
                    and prop.time_interval is not None
                    and prop.time_value is not None
                ):
                    _start_date = (prop.seq_time_value, prop.seq_time_interval)
                    _end_date = (prop.time_value, prop.time_interval)
                    _period = (_start_date, _end_date)
                    _event = (prop.event_type, prop.key)
                    self.add_event_type(_event)
                    _events[
                        (_event, _period)
                    ] = f"event_{idx_label + 1}_from_{self.get_date_column(_start_date)}_to_{self.get_date_column(_end_date)}"

            elif prop.type == "performed_event_regularly":
                # handle regularly intervals
                pass

        return _events

    def events_in_period_to_query(self) -> List[Event_In_Period]:
        return list(self.events_in_period_to_query_column_names.keys())

    def get_event_in_period_column(self, event_in_period: Event_In_Period) -> ColumnName:
        return self.events_in_period_to_query_column_names[event_in_period]

    @cached_property
    def first_time_activity_events_to_query_column_names(self) -> Dict[Event_In_Period, str]:
        _first_time_activity = {}
        for idx, prop in enumerate(self.filter.property_groups.flat):
            idx_label = idx
            if (
                prop.type == "performed_event_first_time"
                and prop.key is not None
                and prop.event_type is not None
                and prop.time_interval is not None
                and prop.time_value is not None
            ):
                _event = (prop.event_type, prop.key)
                self.add_event_type(_event)
                _relative_date = (prop.time_value, prop.time_interval)
                _now = NOW
                _period = (_relative_date, _now)
                _first_time_activity[(_event, _period)] = f"first_time_activity_{idx_label}"

        return _first_time_activity

    def first_time_activity_events_to_query(self) -> List[Event_In_Period]:
        return list(self.first_time_activity_events_to_query_column_names.keys())

    def get_first_time_activity_event_in_period_column(self, event_period: Event_In_Period) -> ColumnName:
        return self.first_time_activity_events_to_query_column_names[(event_period)]

    @cached_property
    def sequences_to_query_column_names(self) -> Dict[Tuple[Event_In_Period, Event, Relative_Date], str]:
        _sequences = {}
        for idx, prop in enumerate(self.filter.property_groups.flat):
            idx_label = idx
            if (
                prop.type == "performed_event_sequence"
                and prop.key is not None
                and prop.event_type is not None
                and prop.time_interval is not None
                and prop.time_value is not None
                and prop.seq_event is not None
                and prop.seq_event_type is not None
                and prop.seq_time_interval is not None
                and prop.seq_time_value is not None
            ):
                _event = (prop.event_type, prop.key)
                _event_period = ((prop.time_value, prop.time_interval), NOW)
                _seq_event = (prop.seq_event_type, prop.seq_event)
                _seq_event_period = (prop.seq_time_value, prop.seq_time_interval)
                self.add_event_type(_event)
                _sequences[((_event, _event_period), _seq_event, _seq_event_period)] = f"sequence_{idx_label}"

        return _sequences

    def get_sequence_column(self, sequence: Tuple[Event_In_Period, Event, Relative_Date]) -> ColumnName:
        return self.sequences_to_query_column_names[sequence]

    def sequences_to_query(self) -> List[Tuple[Event_In_Period, Event, Relative_Date]]:
        return list(self.sequences_to_query_column_names.keys())

    def person_columns_to_query(self) -> Set[ColumnName]:
        return set(
            property_name for property_name, _, _, _ in self._used_properties_with_type_and_operator("person", "OR")
        )

    @cached_property
    def is_using_person_properties_in_or(self) -> bool:
        return len(self.person_columns_to_query()) > 0

    def add_event_type(self, event: Event) -> None:
        if event[0] == "action":
            action = Action.objects.get(id=int(event[1]))
            for step in action.steps.all():
                self._events.append(step.event)
        else:
            self._events.append(event[1])

    def get_events_to_query(self) -> List[str]:
        return list(set(self._events))


class CohortQuery(EnterpriseEventQuery):

    BEHAVIOR_QUERY_ALIAS = "behavior_query"
    _cohort_optimizer: CohortOptimizer

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter, SessionRecordingsFilter],
        team: Team,
        round_interval=False,
        should_join_distinct_ids=False,
        should_join_persons=False,
        # Extra events/person table columns to fetch since parent query needs them
        extra_fields: List[ColumnName] = [],
        extra_event_properties: List[PropertyName] = [],
        extra_person_fields: List[ColumnName] = [],
        override_aggregate_users_by_distinct_id: Optional[bool] = None,
        **kwargs,
    ) -> None:
        self._cohort_optimizer = CohortOptimizer(filter, team.pk)
        super().__init__(
            filter=filter,
            team=team,
            round_interval=round_interval,
            should_join_distinct_ids=should_join_distinct_ids,
            should_join_persons=should_join_persons,
            extra_fields=extra_fields,
            extra_event_properties=extra_event_properties,
            extra_person_fields=extra_person_fields,
            override_aggregate_users_by_distinct_id=override_aggregate_users_by_distinct_id,
            **kwargs,
        )

    def get_query(self) -> Tuple[str, Dict[str, Any]]:

        behavior_subquery, behavior_subquery_params = self._get_behavior_subquery()
        self.params.update(behavior_subquery_params)
        conditions, condition_params = self._get_conditions()
        self.params.update(condition_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        final_query = f"""
        SELECT person_id FROM
        ({behavior_subquery}) {self.BEHAVIOR_QUERY_ALIAS}
        {person_query}
        WHERE team_id = %(team_id)s
        {conditions}
        """

        return final_query, self.params

    def _get_behavior_subquery(self) -> Tuple[str, Dict[str, Any]]:
        """
        Get the subquery for the cohort query.
        """

        _fields = [f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id as person_id"]

        date_fields = self._get_date_fields()
        event_in_period_fields = self._get_event_in_period_fields()
        first_time_activity_fields = self._get_first_time_fields()
        sequence_fields = self._get_sequence_fields()

        _fields.extend(date_fields)
        _fields.extend(event_in_period_fields)
        _fields.extend(first_time_activity_fields)
        _fields.extend(sequence_fields)

        events = self._cohort_optimizer.get_events_to_query()

        query = f"""
        SELECT {", ".join(_fields)} FROM events {self.EVENT_TABLE_ALIAS}
        {self._get_distinct_id_query()}
        WHERE team_id = %(team_id)s
        AND event IN %(events)s
        GROUP BY person_id
        """

        return query, {"team_id": self._team_id, "events": events}

    def _get_person_query(self) -> Tuple[str, Dict]:
        """
        FULL OUTER JOIN because the query needs to account for all people if there are or groups
        """
        if self._should_join_persons:
            person_query, params = self._person_query.get_query()
            return (
                f"""
            FULL OUTER JOIN ({person_query}) {self.PERSON_TABLE_ALIAS}
            ON {self.PERSON_TABLE_ALIAS}.id = {self.BEHAVIOR_QUERY_ALIAS}.person_id
            """,
                params,
            )
        else:
            return "", {}

    # TODO: Build conditions based on property group
    def _get_conditions(self) -> Tuple[str, Dict[str, Any]]:
        def build_conditions(prop: Union[PropertyGroup, Property]):
            if isinstance(prop, PropertyGroup):
                return f" {prop.type} ".join(build_conditions(p) for p in prop.values)
            else:
                return self._get_condition_for_property(prop)

        return build_conditions(self._filter.property_groups), {}

    def _get_condition_for_property(self, prop: Property) -> str:
        if prop.type == "performed_event":
            return self.get_performed_event_condition(prop)
        elif prop.type == "performed_event_muliple":
            return self.get_performed_event_multiple(prop)
        elif prop.type == "stopped_performing_event":
            return self.get_stopped_performing_event(prop)
        elif prop.type == "restarted_performing_event":
            return self.get_restarted_performing_event(prop)
        elif prop.type == "performed_event_first_time":
            return self.get_performed_event_first_time(prop)
        else:
            return ""

    def get_performed_event_condition(self, prop: Property) -> str:
        event = (prop.event_type, prop.key)
        start_date = (prop.time_value, prop.time_interval)
        end_date = NOW
        period = (start_date, end_date)
        column_name = self._cohort_optimizer.get_event_in_period_column((event, period))

        return f"{column_name} > 0"

    def get_performed_event_multiple(self, prop: Property) -> str:
        event = (prop.event_type, prop.key)
        start_date = (prop.time_value, prop.time_interval)
        end_date = NOW
        period = (start_date, end_date)
        count = prop.operator_value

        column_name = self._cohort_optimizer.get_event_in_period_column((event, period))

        return f"{column_name} {get_count_operator(prop.operator)} %(operator_value)s"

    def get_stopped_performing_event(self, prop: Property) -> str:
        event = (prop.event_type, prop.key)
        start_date = (prop.time_value, prop.time_interval)
        end_date = NOW
        period = (start_date, end_date)
        second_period = ((prop.seq_time_value, prop.seq_time_interval), period)

        first_period_column_name = self._cohort_optimizer.get_event_in_period_column((event, period))
        second_period_column_name = self._cohort_optimizer.get_event_in_period_column((event, second_period))

        return f"{first_period_column_name} = 0 AND {second_period_column_name} > 0"

    def get_restarted_performing_event(self, prop: Property) -> str:
        event = (prop.event_type, prop.key)
        start_date = (prop.time_value, prop.time_interval)
        end_date = NOW
        period = (start_date, end_date)
        second_period = ((prop.seq_time_value, prop.seq_time_interval), period)

        first_period_column_name = self._cohort_optimizer.get_event_in_period_column((event, period))
        second_period_column_name = self._cohort_optimizer.get_event_in_period_column((event, second_period))

        return f"{first_period_column_name} > 0 AND {second_period_column_name} = 0"

    def get_performed_event_first_time(self, prop: Property) -> str:
        event = (prop.event_type, prop.key)
        start_date = (prop.time_value, prop.time_interval)
        end_date = NOW
        period = (start_date, end_date)
        column_name = self._cohort_optimizer.get_first_time_activity_event_in_period_column((event, period))

        return f"{column_name} = 1"

    def get_performed_event_sequence(self, prop: Property) -> str:
        event = (prop.event_type, prop.key)
        start_date = (prop.time_value, prop.time_interval)
        end_date = NOW
        period = (start_date, end_date)
        seq_event = (prop.seq_event_type, prop.seq_event)
        seq_date_value = (prop.seq_time_value, prop.seq_time_interval)

        column_name = self._cohort_optimizer.get_sequence_column(((event, period), seq_event, seq_date_value))

        return f"{column_name} = 2"

    def _determine_should_join_distinct_ids(self) -> None:
        self._should_join_distinct_ids = True

    def _determine_should_join_persons(self) -> None:
        return self._cohort_optimizer.is_using_person_properties

    def _get_date_fields(self) -> str:
        fields = []
        dates = self._cohort_optimizer.dates_to_query()

        for date in dates:
            if date == NOW:
                fields += [f"now() as {self._cohort_optimizer.get_date_column(date)}"]
            else:
                fields += [
                    f"{self._cohort_optimizer.get_date_column(NOW)} - INTERVAL {date[0]} {date[1]} AS {self._cohort_optimizer.get_date_column(date)}"
                ]

        return fields

    def _get_event_in_period_fields(self) -> str:
        fields = []
        event_periods = self._cohort_optimizer.events_in_period_to_query()

        for event_period in event_periods:
            # TODO: handle indexing of event params
            event = event_period[0]
            entity_query, entity_params = self._get_entity(event)
            period = event_period[1]
            start_date_column = self._cohort_optimizer.get_date_column(period[0])
            end_date_column = self._cohort_optimizer.get_date_column(period[1])
            fields += [
                f"countIf(timestamp > {start_date_column} AND timestamp < {end_date_column} AND {entity_query}) as {self._cohort_optimizer.get_event_in_period_column(event_period)}"
            ]

        return fields

    def _get_first_time_fields(self) -> str:
        fields = []
        first_times = self._cohort_optimizer.first_time_activity_events_to_query()

        for first_time_event_period in first_times:
            # TODO: handle indexing of event params
            event = first_time_event_period[0]
            entity_query, entity_params = self._get_entity(event)
            period = first_time_event_period[1]

            fields += [
                f"""if(minIf(timestamp, {entity_query}) >= {self._cohort_optimizer.get_date_column(period[0])} AND minIf(timestamp, {entity_query}) < {self._cohort_optimizer.get_date_column(period[1])}, 1, 0) as {self._cohort_optimizer.get_first_time_activity_event_in_period_column(first_time_event_period)}"""
            ]

        return fields

    def _get_sequence_fields(self) -> str:
        fields = []
        sequences = self._cohort_optimizer.sequences_to_query()

        for sequence in sequences:
            # TODO: handle indexing of event params
            event_period = sequence[0]
            event = event_period[0]
            period = event_period[1]
            entity_query, entity_params = self._get_entity(event)
            seq_event = sequence[1]
            seq_entity_query, seq_entity_params = self._get_entity(seq_event)
            relative_date = sequence[2]

            fields += [
                f"""windowFunnel({relative_date_to_seconds(relative_date)})(toDateTime(timestamp), {entity_query} AND now() - INTERVAL {period[0]} {period[1]}, {seq_entity_query}) as {self._cohort_optimizer.get_sequence_column(sequence)}"""
            ]

        return fields

    def _get_entity(self, event: Event) -> Tuple[str, Dict[str, Any]]:
        # TODO: handle indexing of event params
        if event[0] == "action":
            return get_entity_query(None, int(event[1]), self._team_id, "test")
        elif event[0] == "event":
            return get_entity_query(str(event[1]), None, self._team_id, "test")
        else:
            return "", {}


INTERVAL_TO_SECONDS = {
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,
}


def relative_date_to_seconds(date: Relative_Date):
    if date == NOW:
        return 0
    else:
        return date[0] * INTERVAL_TO_SECONDS[date[1]]
