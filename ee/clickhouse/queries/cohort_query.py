from typing import Any, Dict, List, Optional, Tuple, Union

from ee.clickhouse.materialized_columns.columns import ColumnName
from ee.clickhouse.models.cohort import get_count_operator, get_entity_query
from ee.clickhouse.models.property import prop_filter_json_extract
from ee.clickhouse.queries.event_query import EnterpriseEventQuery
from posthog.models import Filter, Team
from posthog.models.action import Action
from posthog.models.property import OperatorInterval, Property, PropertyGroup, PropertyName

Relative_Date = Tuple[int, OperatorInterval]
Event = Tuple[str, Union[str, int]]


INTERVAL_TO_SECONDS = {
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,
    "year": 31536000,
}


def relative_date_to_seconds(date: Tuple[Optional[int], Union[OperatorInterval, None]]):
    if date[0] is None or date[1] is None:
        raise ValueError("Time value and time interval must be specified")

    return date[0] * INTERVAL_TO_SECONDS[date[1]]


def validate_interval(interval: Optional[OperatorInterval]) -> str:
    if interval is None or interval not in INTERVAL_TO_SECONDS.keys():
        raise ValueError(f"Invalid interval: {interval}")
    else:
        return interval


def parse_and_validate_positive_integer(value: Optional[int], value_name: str) -> int:
    if value is None:
        raise ValueError(f"{value_name} cannot be None")
    try:
        parsed_value = int(value)
    except ValueError:
        raise ValueError(f"{value_name} must be an integer, got {value}")
    if parsed_value < 0:
        raise ValueError(f"{value_name} must be greater than 0, got {value}")
    return parsed_value


def relative_date_is_greater(date_1: Relative_Date, date_2: Relative_Date) -> bool:
    if date_1[1] == date_2[1]:
        return date_1[0] > date_2[0]

    return relative_date_to_seconds(date_1) > relative_date_to_seconds(date_2)


class CohortQuery(EnterpriseEventQuery):

    BEHAVIOR_QUERY_ALIAS = "behavior_query"
    _fields: List[str]
    _events: List[str]

    def __init__(
        self,
        filter: Filter,
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
        self._fields = []
        self._events = []
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

        property_groups = self._column_optimizer.property_optimizer.parse_property_groups(self._filter.property_groups)
        self._inner_property_groups = property_groups.inner
        self._outer_property_groups = property_groups.outer

    def get_query(self) -> Tuple[str, Dict[str, Any]]:

        if not self._outer_property_groups:
            # everything is pushed down, no behavioural stuff to do
            # thus, use personQuery directly
            return self._person_query.get_query()

        # TODO: clean up this kludge. Right now, get_conditions has to run first so that _fields is populated for _get_behavioral_subquery()
        conditions, condition_params = self._get_conditions()
        self.params.update(condition_params)

        behavior_subquery, behavior_subquery_params = self._get_behavior_subquery()
        self.params.update(behavior_subquery_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        # Since we can FULL OUTER JOIN, we may end up with pairs of uuids where one side is blank. Always try to choose the non blank ID
        select_field = (
            f"if(person_id = '00000000-0000-0000-0000-000000000000', {self.PERSON_TABLE_ALIAS}.id, person_id)"
            if self._should_join_persons
            else "person_id"
        )

        final_query = f"""
        SELECT {select_field} AS id FROM
        ({behavior_subquery}) {self.BEHAVIOR_QUERY_ALIAS}
        {person_query}
        WHERE 1 = 1
        {conditions}
        """

        return final_query, self.params

    def _get_behavior_subquery(self) -> Tuple[str, Dict[str, Any]]:
        #
        # Get the subquery for the cohort query.
        #

        _fields = [f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id as person_id"]
        _fields.extend(self._fields)

        date_query, date_params = self._get_date_query()

        query = f"""
        SELECT {", ".join(_fields)} FROM events {self.EVENT_TABLE_ALIAS}
        {self._get_distinct_id_query()}
        WHERE team_id = %(team_id)s
        AND event IN %(events)s
        {date_query}
        GROUP BY person_id
        """

        return (
            query,
            {"team_id": self._team_id, "events": self._events, **date_params,},
        )

    def _get_person_query(self) -> Tuple[str, Dict]:
        if self._should_join_persons:
            person_query, params = self._person_query.get_query()

            if "person" not in [prop.type for prop in getattr(self._outer_property_groups, "flat", [])]:
                # No outer group properties relate to persons, so inner join is sufficient
                return (
                    f"""
                    INNER JOIN ({person_query}) {self.PERSON_TABLE_ALIAS}
                    ON {self.PERSON_TABLE_ALIAS}.id = {self.BEHAVIOR_QUERY_ALIAS}.person_id
                    """,
                    params,
                )
            else:
                # FULL OUTER JOIN because the query needs to account for all people if there are or groups
                return (
                    f"""
                FULL OUTER JOIN ({person_query}) {self.PERSON_TABLE_ALIAS}
                ON {self.PERSON_TABLE_ALIAS}.id = {self.BEHAVIOR_QUERY_ALIAS}.person_id
                """,
                    params,
                )
        else:
            return "", {}

    def _get_date_query(self) -> Tuple[str, Dict[str, Any]]:
        # TODO: handle as params
        return "", {}

    # TODO: Build conditions based on property group
    def _get_conditions(self) -> Tuple[str, Dict[str, Any]]:
        def build_conditions(prop: Optional[Union[PropertyGroup, Property]], prepend="level", num=0):
            if not prop:
                return "", {}

            if isinstance(prop, PropertyGroup):
                params = {}
                conditions = []
                for idx, p in enumerate(prop.values):
                    q, q_params = build_conditions(p, f"{prepend}_level", idx)  # type: ignore
                    if q != "":
                        conditions.append(q)
                        params.update(q_params)

                return f"({f' {prop.type} '.join(conditions)})", params
            else:
                return self._get_condition_for_property(prop, prepend, num)

        conditions, params = build_conditions(self._outer_property_groups, prepend="level", num=0)
        return f"AND ({conditions})" if conditions else "", params

    def _get_condition_for_property(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:

        res: str = ""
        params: Dict[str, Any] = {}

        if prop.type == "behavioural":
            if prop.value == "performed_event":
                res, params = self.get_performed_event_condition(prop, prepend, idx)
            elif prop.value == "performed_event_multiple":
                res, params = self.get_performed_event_multiple(prop, prepend, idx)
            elif prop.value == "stopped_performing_event":
                res, params = self.get_stopped_performing_event(prop, prepend, idx)
            elif prop.value == "restarted_performing_event":
                res, params = self.get_restarted_performing_event(prop, prepend, idx)
            elif prop.value == "performed_event_first_time":
                res, params = self.get_performed_event_first_time(prop, prepend, idx)
            elif prop.value == "performed_event_sequence":
                res, params = self.get_performed_event_sequence(prop, prepend, idx)
            elif prop.value == "performed_event_regularly":
                res, params = self.get_performed_event_regularly(prop, prepend, idx)
        elif prop.type == "person":
            res, params = self.get_person_condition(prop, prepend, idx)
        else:
            raise ValueError(f"Invalid property type for Cohort queries: {prop.type}")

        return res, params

    def get_person_condition(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        # TODO: handle if props are pushed down in PersonQuery
        if len(self._outer_property_groups.flat):
            return prop_filter_json_extract(
                prop, idx, prepend, prop_var="person_props", allow_denormalized_props=True, property_operator=""
            )
        else:
            return "", {}

    def get_performed_event_condition(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        event = (prop.event_type, prop.key)
        column_name = f"performed_event_condition_{prepend}_{idx}"

        entity_query, entity_params = self._get_entity(event, prepend, idx)
        date_value = prop.time_value
        date_param = f"{prepend}_date_{idx}"
        date_interval = validate_interval(prop.time_interval)
        field = f"countIf(timestamp > now() - INTERVAL %({date_param})s {date_interval} AND timestamp < now() AND {entity_query}) AS {column_name}"
        self._fields.append(field)

        return f"{column_name} > 0", {f"{date_param}": date_value, **entity_params}

    def get_performed_event_multiple(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        event = (prop.event_type, prop.key)
        column_name = f"performed_event_multiple_condition_{prepend}_{idx}"

        entity_query, entity_params = self._get_entity(event, prepend, idx)
        count = prop.operator_value
        date_value = prop.time_value
        date_param = f"{prepend}_date_{idx}"
        date_interval = validate_interval(prop.time_interval)
        field = f"countIf(timestamp > now() - INTERVAL %({date_param})s {date_interval} AND timestamp < now() AND {entity_query}) AS {column_name}"
        self._fields.append(field)

        return (
            f"{column_name} {get_count_operator(prop.operator)} %(operator_value)s",
            {"operator_value": count, f"{date_param}": date_value, **entity_params},
        )

    def get_stopped_performing_event(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        event = (prop.event_type, prop.key)
        before_column_name = f"stopped_event_condition_{prepend}_{idx}_before"
        after_column_name = f"stopped_event_condition_{prepend}_{idx}_after"

        entity_query, entity_params = self._get_entity(event, prepend, idx)
        date_value = prop.time_value
        date_param = f"{prepend}_date_{idx}"
        date_interval = validate_interval(prop.time_interval)

        seq_date_value = prop.seq_time_value
        seq_date_param = f"{prepend}_seq_date_{idx}"
        seq_date_interval = validate_interval(prop.seq_time_interval)

        before_field = f"countIf(timestamp > now() - INTERVAL %({date_param})s {date_interval} - INTERVAL %({seq_date_param})s {seq_date_interval} AND timestamp < now() - INTERVAL %({date_param})s {date_interval} AND {entity_query}) AS {before_column_name}"
        after_field = f"countIf(timestamp > now() - INTERVAL %({date_param})s {date_interval} AND timestamp < now() AND {entity_query}) AS {after_column_name}"

        self._fields.append(before_field)
        self._fields.append(after_field)

        return (
            f"({after_column_name} = 0 AND {before_column_name} > 0)",
            {f"{date_param}": date_value, f"{seq_date_param}": seq_date_value, **entity_params},
        )

    def get_restarted_performing_event(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        event = (prop.event_type, prop.key)
        before_column_name = f"restarted_event_condition_{prepend}_{idx}_before"
        after_column_name = f"restarted_event_condition_{prepend}_{idx}_after"

        entity_query, entity_params = self._get_entity(event, prepend, idx)
        date_value = prop.time_value
        date_param = f"{prepend}_date_{idx}"
        date_interval = validate_interval(prop.time_interval)

        seq_date_value = prop.seq_time_value
        seq_date_param = f"{prepend}_seq_date_{idx}"
        seq_date_interval = validate_interval(prop.seq_time_interval)

        before_field = f"countIf(timestamp > now() - INTERVAL %({date_param})s {date_interval} - INTERVAL %({seq_date_param})s {seq_date_interval} AND timestamp < now() - INTERVAL %({date_param})s {date_interval} AND {entity_query}) AS {before_column_name}"
        after_field = f"countIf(timestamp > now() - INTERVAL %({date_param})s {date_interval} AND timestamp < now() AND {entity_query}) AS {after_column_name}"

        self._fields.append(before_field)
        self._fields.append(after_field)

        return (
            f"({before_column_name} = 0 AND {after_column_name} > 0)",
            {f"{date_param}": date_value, f"{seq_date_param}": seq_date_value, **entity_params},
        )

    def get_performed_event_first_time(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        event = (prop.event_type, prop.key)
        entity_query, entity_params = self._get_entity(event, prepend, idx)

        column_name = f"first_time_condition_{prepend}_{idx}"

        date_value = prop.time_value
        date_param = f"{prepend}_date_{idx}"
        date_interval = validate_interval(prop.time_interval)

        field = f"""if(minIf(timestamp, {entity_query}) >= now() - INTERVAL %({date_param})s {date_interval} AND minIf(timestamp, {entity_query}) < now(), 1, 0) as {column_name}"""

        self._fields.append(field)

        return f"{column_name} = 1", {f"{date_param}": date_value, **entity_params}

    def get_performed_event_sequence(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        event = (prop.event_type, prop.key)
        entity_query, entity_params = self._get_entity(event, prepend, idx)

        column_name = f"event_sequence_condition_{prepend}_{idx}"

        date_value = prop.time_value
        date_param = f"{prepend}_date_{idx}"
        date_interval = validate_interval(prop.time_interval)

        seq_event = (prop.seq_event_type, prop.seq_event)
        seq_entity_query, seq_entity_params = self._get_entity(seq_event, f"{prepend}_seq", idx)
        seq_date_value = (prop.seq_time_value, prop.seq_time_interval)

        field = f"""windowFunnel({relative_date_to_seconds(seq_date_value)})(toDateTime(timestamp), {entity_query} AND timestamp >= now() - INTERVAL %({date_value})s {date_interval}, {seq_entity_query}) AS {column_name}"""

        self._fields.append(field)

        return f"{column_name} = 2", {f"{date_param}": date_value, **entity_params, **seq_entity_params}

    def get_performed_event_regularly(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        event = (prop.event_type, prop.key)
        entity_query, entity_params = self._get_entity(event, prepend, idx)

        column_name = f"performed_event_regularly_{prepend}_{idx}"

        date_interval = validate_interval(prop.time_interval)

        time_value_param = f"{prepend}_time_value_{idx}"
        time_value = parse_and_validate_positive_integer(prop.time_value, "time_value")

        operator_value_param = f"{prepend}_operator_value_{idx}"
        operator_value = parse_and_validate_positive_integer(prop.operator_value, "operator_value")

        min_periods_param = f"{prepend}_min_periods_{idx}"
        min_periods = parse_and_validate_positive_integer(prop.min_periods, "min_periods")

        params = {
            time_value_param: time_value,
            operator_value_param: operator_value,
            min_periods_param: min_periods,
        }
        periods = []

        if prop.total_periods:
            for period in range(prop.total_periods):
                start_time_value = f"%({time_value_param})s * {period}"
                end_time_value = f"%({time_value_param})s * ({period} + 1)"
                # Clause that returns 1 if the event was performed the expected number of times in the given time interval, otherwise 0
                periods.append(
                    f"if(countIf({entity_query} and timestamp <= now() - INTERVAL {start_time_value} {date_interval} and timestamp > now() - INTERVAL {end_time_value} {date_interval}) {get_count_operator(prop.operator)} %({operator_value_param})s, 1, 0)"
                )

        field = "+".join(periods) + f">= %({min_periods_param})s" + f" as {column_name}"

        self._fields.append(field)

        return column_name, {**entity_params, **params}

    def _determine_should_join_distinct_ids(self) -> None:
        self._should_join_distinct_ids = True

    def _determine_should_join_persons(self) -> None:
        self._should_join_persons = self._column_optimizer.is_using_person_properties

    def _get_entity(
        self, event: Tuple[Optional[str], Optional[Union[int, str]]], prepend: str, idx: int
    ) -> Tuple[str, Dict[str, Any]]:
        # TODO: handle indexing of event params
        res: str = ""
        params: Dict[str, Any] = {}

        if event[0] is None or event[1] is None:
            raise ValueError("Event type and key must be specified")

        if event[0] == "actions":
            self._add_action(int(event[1]))
            res, params = get_entity_query(None, int(event[1]), self._team_id, f"{prepend}_entity_{idx}")
        elif event[0] == "events":
            self._add_event(str(event[1]))
            res, params = get_entity_query(str(event[1]), None, self._team_id, f"{prepend}_entity_{idx}")
        else:
            raise ValueError(f"Event type must be 'events' or 'actions'")

        return res, params

    def _add_action(self, action_id: int) -> None:
        action = Action.objects.get(id=action_id)
        for step in action.steps.all():
            self._events.append(step.event)

    def _add_event(self, event_id: str) -> None:
        self._events.append(event_id)
