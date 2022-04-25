from typing import Any, Dict, List, Optional, Tuple, Union

from ee.clickhouse.materialized_columns.columns import ColumnName
from ee.clickhouse.models.cohort import format_filter_query, get_count_operator, get_entity_query
from ee.clickhouse.models.property import prop_filter_json_extract
from ee.clickhouse.queries.event_query import EnterpriseEventQuery
from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from posthog.constants import INSIGHT_FUNNELS
from posthog.models import Filter, Team
from posthog.models.action import Action
from posthog.models.cohort import Cohort
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property import BehaviouralPropertyType, OperatorInterval, Property, PropertyGroup, PropertyName

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


def validate_interval(interval: Optional[OperatorInterval]) -> OperatorInterval:
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
    if parsed_value <= 0:
        raise ValueError(f"{value_name} must be greater than 0, got {value}")
    return parsed_value


def validate_entity(possible_event: Tuple[Optional[str], Optional[Union[int, str]]]) -> Event:
    event_type = possible_event[0]
    event_val = possible_event[1]
    if event_type is None or event_val is None:
        raise ValueError("Entity name and entity id must be specified")
    return (event_type, event_val)


def validate_seq_date_more_recent_than_date(seq_date: Relative_Date, date: Relative_Date):
    if relative_date_is_greater(seq_date, date):
        raise ValueError("seq_date must be more recent than date")


def relative_date_is_greater(date_1: Relative_Date, date_2: Relative_Date) -> bool:
    return relative_date_to_seconds(date_1) > relative_date_to_seconds(date_2)


def convert_to_entity_params(events: List[Event]) -> Tuple[List, List]:
    res_events = []
    res_actions = []

    for idx, event in enumerate(events):
        event_type = event[0]
        event_val = event[1]

        if event_type == "events":
            res_events.append(
                {"id": event_val, "name": event_val, "order": idx, "type": event_type,}
            )
        elif event_type == "actions":
            action = Action.objects.get(id=event_val)
            res_actions.append(
                {"id": event_val, "name": action.name, "order": idx, "type": event_type,}
            )

    return res_events, res_actions


def get_relative_date_arg(relative_date: Relative_Date) -> str:
    return f"-{relative_date[0]}{relative_date[1][0].lower()}"


def full_outer_join_query(q: str, alias: str, left_operand: str, right_operand: str) -> str:
    return join_query(q, "FULL OUTER JOIN", alias, left_operand, right_operand)


def inner_join_query(q: str, alias: str, left_operand: str, right_operand: str) -> str:
    return join_query(q, "INNER JOIN", alias, left_operand, right_operand)


def join_query(q: str, join: str, alias: str, left_operand: str, right_operand: str) -> str:
    return f"{join} ({q}) {alias} ON {left_operand} = {right_operand}"


def if_condition(condition: str, true_res: str, false_res: str) -> str:
    return f"if({condition}, {true_res}, {false_res})"


class CohortQuery(EnterpriseEventQuery):

    BEHAVIOR_QUERY_ALIAS = "behavior_query"
    FUNNEL_QUERY_ALIAS = "funnel_query"
    _fields: List[str]
    _events: List[str]
    _earliest_time_for_event_query: Union[Relative_Date, None]
    _restrict_event_query_by_time: bool

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
        self._earliest_time_for_event_query = None
        self._restrict_event_query_by_time = True
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

        self._validate_negations()

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

        subq = []

        behavior_subquery, behavior_subquery_params, behavior_query_alias = self._get_behavior_subquery()
        subq.append((behavior_subquery, behavior_query_alias))
        self.params.update(behavior_subquery_params)

        person_query, person_params, person_query_alias = self._get_persons_query()
        subq.append((person_query, person_query_alias))
        self.params.update(person_params)

        sequence_query, sequence_params, sequence_query_alias = self._get_sequence_query()
        subq.append((sequence_query, sequence_query_alias))
        self.params.update(sequence_params)

        # Since we can FULL OUTER JOIN, we may end up with pairs of uuids where one side is blank. Always try to choose the non blank ID
        q, fields = self._build_sources(subq)

        final_query = f"""
        SELECT {fields} AS id FROM
        {q}
        WHERE 1 = 1
        {conditions}
        """

        return final_query, self.params

    def _build_sources(self, subq: List[Tuple[str, str]]) -> Tuple[str, str]:
        q = ""
        filtered_queries = [(q, alias) for (q, alias) in subq if q and len(q)]

        prev_alias: Optional[str] = None
        fields = ""
        for idx, (subq_query, subq_alias) in enumerate(filtered_queries):
            if idx == 0:
                q += f"({subq_query}) {subq_alias}"
                fields = f"{subq_alias}.person_id"
            elif prev_alias:  # can't join without a previous alias
                q = f"{q} {full_outer_join_query(subq_query, subq_alias, f'{subq_alias}.person_id', f'{prev_alias}.person_id')}"
                fields = if_condition(
                    f"{prev_alias}.person_id = '00000000-0000-0000-0000-000000000000'",
                    f"{subq_alias}.person_id",
                    f"{fields}",
                )
            prev_alias = subq_alias

        return q, fields

    def _get_behavior_subquery(self) -> Tuple[str, Dict[str, Any], str]:
        #
        # Get the subquery for the cohort query.
        #

        query, params = "", {}
        if self._should_join_behavioral_query:

            _fields = [f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id AS person_id"]
            _fields.extend(self._fields)

            date_condition, date_params = self._get_date_condition()

            query = f"""
            SELECT {", ".join(_fields)} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_distinct_id_query()}
            WHERE team_id = %(team_id)s
            AND event IN %(events)s
            {date_condition}
            GROUP BY person_id
            """

            query, params = (query, {"team_id": self._team_id, "events": self._events, **date_params,})

        return query, params, self.BEHAVIOR_QUERY_ALIAS

    def _get_persons_query(self) -> Tuple[str, Dict[str, Any], str]:
        query, params = "", {}
        if self._should_join_persons:
            person_query, person_params = self._person_query.get_query()
            person_query = f"SELECT *, id AS person_id FROM ({person_query})"

            query, params = person_query, person_params

        return query, params, self.PERSON_TABLE_ALIAS

    def _get_date_condition(self) -> Tuple[str, Dict[str, Any]]:
        # TODO: handle as params
        date_query = ""
        date_params: Dict[str, Any] = {}

        if self._earliest_time_for_event_query and self._restrict_event_query_by_time:
            date_params = {"earliest_time": self._earliest_time_for_event_query[0]}
            date_query = f"AND timestamp <= now() AND timestamp >= now() - INTERVAL %(earliest_time)s {self._earliest_time_for_event_query[1]}"

        return date_query, date_params

    def _check_earliest_date(self, relative_date: Relative_Date) -> None:
        if self._earliest_time_for_event_query is None:
            self._earliest_time_for_event_query = relative_date
        elif relative_date_is_greater(relative_date, self._earliest_time_for_event_query):
            self._earliest_time_for_event_query = relative_date

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
                # TODO: implement this condition
                pass
            elif prop.value == "performed_event_regularly":
                res, params = self.get_performed_event_regularly(prop, prepend, idx)
        elif prop.type == "person":
            res, params = self.get_person_condition(prop, prepend, idx)
        elif prop.type == "cohort":
            res, params = self.get_cohort_condition(prop, prepend, idx)
        else:
            raise ValueError(f"Invalid property type for Cohort queries: {prop.type}")

        return res, params

    def get_person_condition(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        # TODO: handle if props are pushed down in PersonQuery
        if self._outer_property_groups and len(self._outer_property_groups.flat):
            return prop_filter_json_extract(
                prop, idx, prepend, prop_var="person_props", allow_denormalized_props=True, property_operator=""
            )
        else:
            return "", {}

    def get_cohort_condition(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:

        q, params = "", {}
        try:
            prop_cohort: Cohort = Cohort.objects.get(pk=prop.value, team_id=self._team_id)
        except Cohort.DoesNotExist:
            q = "0 = 14"

        # TODO: renable this check when this class accepts a cohort not filter

        # if prop_cohort.pk == cohort.pk:
        #     # If we've encountered a cyclic dependency (meaning this cohort depends on this cohort),
        #     # we treat it as satisfied for all persons
        #     pass
        # else:

        # TODO: format_filter_query uses the deprecated way of building cohorts
        # Update format_filter_query to use this class or use this class directly when backwards compatibility is achieved
        # This function will only work for old cohorts right now
        person_id_query, cohort_filter_params = format_filter_query(prop_cohort, idx, "person_id")
        q = f"id IN ({person_id_query})"
        params = cohort_filter_params

        return q, params

    def get_performed_event_condition(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        event = (prop.event_type, prop.key)
        column_name = f"performed_event_condition_{prepend}_{idx}"

        entity_query, entity_params = self._get_entity(event, prepend, idx)
        date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        date_interval = validate_interval(prop.time_interval)
        date_param = f"{prepend}_date_{idx}"

        self._check_earliest_date((date_value, date_interval))

        field = f"countIf(timestamp > now() - INTERVAL %({date_param})s {date_interval} AND timestamp < now() AND {entity_query}) > 0 AS {column_name}"
        self._fields.append(field)

        return column_name, {f"{date_param}": date_value, **entity_params}

    def get_performed_event_multiple(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        event = (prop.event_type, prop.key)
        column_name = f"performed_event_multiple_condition_{prepend}_{idx}"

        entity_query, entity_params = self._get_entity(event, prepend, idx)
        count = parse_and_validate_positive_integer(prop.operator_value, "operator_value")
        date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        date_interval = validate_interval(prop.time_interval)
        date_param = f"{prepend}_date_{idx}"

        self._check_earliest_date((date_value, date_interval))

        field = f"countIf(timestamp > now() - INTERVAL %({date_param})s {date_interval} AND timestamp < now() AND {entity_query}) {get_count_operator(prop.operator)} %(operator_value)s AS {column_name}"
        self._fields.append(field)

        return (
            column_name,
            {"operator_value": count, f"{date_param}": date_value, **entity_params},
        )

    def get_stopped_performing_event(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        event = (prop.event_type, prop.key)
        column_name = f"stopped_event_condition_{prepend}_{idx}"

        entity_query, entity_params = self._get_entity(event, prepend, idx)
        date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        date_param = f"{prepend}_date_{idx}"
        date_interval = validate_interval(prop.time_interval)

        seq_date_value = parse_and_validate_positive_integer(prop.seq_time_value, "time_value")
        seq_date_param = f"{prepend}_seq_date_{idx}"
        seq_date_interval = validate_interval(prop.seq_time_interval)

        validate_seq_date_more_recent_than_date((seq_date_value, seq_date_interval), (date_value, date_interval))

        self._check_earliest_date((date_value, date_interval))

        # The user was doing the event in this time period
        event_was_happening_period = f"countIf(timestamp > now() - INTERVAL %({date_param})s {date_interval} AND timestamp <= now() - INTERVAL %({seq_date_param})s {seq_date_interval} AND {entity_query})"
        # Then stopped in this time period
        event_stopped_period = f"countIf(timestamp > now() - INTERVAL %({seq_date_param})s {seq_date_interval} AND timestamp <= now() AND {entity_query})"

        full_condition = f"({event_was_happening_period} > 0 AND {event_stopped_period} = 0) as {column_name}"

        self._fields.append(full_condition)

        return (
            column_name,
            {f"{date_param}": date_value, f"{seq_date_param}": seq_date_value, **entity_params},
        )

    def get_restarted_performing_event(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        event = (prop.event_type, prop.key)
        column_name = f"restarted_event_condition_{prepend}_{idx}"

        entity_query, entity_params = self._get_entity(event, prepend, idx)
        date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        date_param = f"{prepend}_date_{idx}"
        date_interval = validate_interval(prop.time_interval)

        seq_date_value = parse_and_validate_positive_integer(prop.seq_time_value, "time_value")
        seq_date_param = f"{prepend}_seq_date_{idx}"
        seq_date_interval = validate_interval(prop.seq_time_interval)

        validate_seq_date_more_recent_than_date((seq_date_value, seq_date_interval), (date_value, date_interval))

        self._restrict_event_query_by_time = False

        # Events should have been fired in the initial_period
        initial_period = f"countIf(timestamp <= now() - INTERVAL %({date_param})s {date_interval} AND {entity_query})"
        # Then stopped in the event_stopped_period
        event_stopped_period = f"countIf(timestamp > now() - INTERVAL %({date_param})s {date_interval} AND timestamp <= now() - INTERVAL %({seq_date_param})s {seq_date_interval} AND {entity_query})"
        # Then restarted in the final event_restart_period
        event_restarted_period = f"countIf(timestamp > now() - INTERVAL %({seq_date_param})s {seq_date_interval} AND timestamp <= now() AND {entity_query})"

        full_condition = (
            f"({initial_period} > 0 AND {event_stopped_period} = 0 AND {event_restarted_period} > 0) as {column_name}"
        )

        self._fields.append(full_condition)

        return (
            column_name,
            {f"{date_param}": date_value, f"{seq_date_param}": seq_date_value, **entity_params},
        )

    def get_performed_event_first_time(self, prop: Property, prepend: str, idx: int) -> Tuple[str, Dict[str, Any]]:
        event = (prop.event_type, prop.key)
        entity_query, entity_params = self._get_entity(event, prepend, idx)

        column_name = f"first_time_condition_{prepend}_{idx}"

        date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        date_param = f"{prepend}_date_{idx}"
        date_interval = validate_interval(prop.time_interval)

        self._restrict_event_query_by_time = False

        field = f"minIf(timestamp, {entity_query}) >= now() - INTERVAL %({date_param})s {date_interval} AND minIf(timestamp, {entity_query}) < now() as {column_name}"

        self._fields.append(field)

        return column_name, {f"{date_param}": date_value, **entity_params}

    @cached_property
    def sequence_filter_to_query(self) -> Optional[Property]:
        for prop in self._filter.property_groups.flat:
            if prop.value == "performed_event_sequence":
                return prop
        return None

    def _get_sequence_query(self) -> Tuple[str, Dict[str, Any], str]:
        query, params = "", {}

        if self.sequence_filter_to_query:
            prop = self.sequence_filter_to_query
            event = validate_entity((prop.event_type, prop.key))
            seq_event = validate_entity((prop.seq_event_type, prop.seq_event))

            time_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
            time_interval = validate_interval(prop.time_interval)
            seq_date_value = parse_and_validate_positive_integer(prop.seq_time_value, "time_value")
            seq_date_interval = validate_interval(prop.seq_time_interval)

            events, actions = convert_to_entity_params([event, seq_event])
            new_filter = Filter(
                data={
                    "insight": INSIGHT_FUNNELS,
                    "funnel_window_interval": seq_date_value,
                    "funnel_window_interval_unit": seq_date_interval,
                    "events": events,
                    "actions": actions,
                    "filter_test_accounts": self._filter.filter_test_accounts,
                    "display": "FunnelViz",
                    "funnel_viz_type": "steps",
                    "date_from": get_relative_date_arg((time_value, time_interval)),
                }
            )

            team = Team.objects.get(id=self._team_id)
            funnel_builder = ClickhouseFunnel(new_filter, team)
            funnel_query = funnel_builder.get_step_counts_query()
            params = funnel_builder.params

            query = f"""
            SELECT aggregation_target AS person_id, steps FROM (
                {funnel_query}
            ) WHERE steps = 2
            """

        return query, params, self.FUNNEL_QUERY_ALIAS

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
        min_period_count = parse_and_validate_positive_integer(prop.min_periods, "min_periods")

        total_period_count = parse_and_validate_positive_integer(prop.total_periods, "total_periods")

        if min_period_count > total_period_count:
            raise (
                ValueError(
                    f"min_periods ({min_period_count}) cannot be greater than total_periods ({total_period_count})"
                )
            )

        params = {
            time_value_param: time_value,
            operator_value_param: operator_value,
            min_periods_param: min_period_count,
        }
        periods = []

        if total_period_count:
            for period in range(total_period_count):
                start_time_value = f"%({time_value_param})s * {period}"
                end_time_value = f"%({time_value_param})s * ({period} + 1)"
                # Clause that returns 1 if the event was performed the expected number of times in the given time interval, otherwise 0
                periods.append(
                    f"if(countIf({entity_query} and timestamp <= now() - INTERVAL {start_time_value} {date_interval} and timestamp > now() - INTERVAL {end_time_value} {date_interval}) {get_count_operator(prop.operator)} %({operator_value_param})s, 1, 0)"
                )
        earliest_date = (total_period_count * time_value, date_interval)
        self._check_earliest_date(earliest_date)

        field = "+".join(periods) + f">= %({min_periods_param})s" + f" as {column_name}"

        self._fields.append(field)

        return column_name, {**entity_params, **params}

    def _determine_should_join_distinct_ids(self) -> None:
        self._should_join_distinct_ids = True

    def _determine_should_join_persons(self) -> None:
        self._should_join_persons = (
            self._column_optimizer.is_using_person_properties or self._column_optimizer.is_using_cohort_propertes
        )

    @cached_property
    def _should_join_behavioral_query(self) -> bool:
        for prop in self._filter.property_groups.flat:
            if prop.value in [
                BehaviouralPropertyType.PERFORMED_EVENT,
                BehaviouralPropertyType.PERFORMED_EVENT_FIRST_TIME,
                BehaviouralPropertyType.PERFORMED_EVENT_MULTIPLE,
                BehaviouralPropertyType.PERFORMED_EVENT_REGULARLY,
                BehaviouralPropertyType.RESTARTED_PERFORMING_EVENT,
                BehaviouralPropertyType.STOPPED_PERFORMING_EVENT,
            ]:
                return True
        return False

    # Check if negations are always paired with a positive filter
    # raise a value error warning that this is an invalid cohort
    def _validate_negations(self) -> None:
        def is_secondary_clause(prop: PropertyGroup):
            if len(prop.values) and isinstance(prop.values[0], PropertyGroup):
                for p in prop.values:
                    if isinstance(p, PropertyGroup):
                        is_secondary_clause(p)
            else:
                has_negation = False
                has_primary_clause = False
                for p in prop.values:
                    if isinstance(p, Property):
                        if p.negation:
                            has_negation = True
                        else:
                            has_primary_clause = True

                if has_negation and not has_primary_clause:
                    raise ValueError("Negations must be paired with a positive filter.")

        is_secondary_clause(self._filter.property_groups)

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
