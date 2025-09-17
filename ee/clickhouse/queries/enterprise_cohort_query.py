from typing import Any, cast

from posthog.schema import PersonsOnEventsMode

from posthog.constants import PropertyOperatorType
from posthog.models.cohort.util import get_count_operator
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property.property import Property, PropertyGroup
from posthog.queries.foss_cohort_query import (
    FOSSCohortQuery,
    parse_and_validate_positive_integer,
    validate_entity,
    validate_interval,
    validate_seq_date_more_recent_than_date,
)
from posthog.queries.util import PersonPropertiesMode


def check_negation_clause(prop: PropertyGroup) -> tuple[bool, bool]:
    has_negation_clause = False
    has_primary_clase = False
    if len(prop.values):
        if isinstance(prop.values[0], PropertyGroup):
            for p in cast(list[PropertyGroup], prop.values):
                has_neg, has_primary = check_negation_clause(p)
                has_negation_clause = has_negation_clause or has_neg
                has_primary_clase = has_primary_clase or has_primary

        else:
            for property in cast(list[Property], prop.values):
                if property.negation:
                    has_negation_clause = True
                else:
                    has_primary_clase = True

        if prop.type == PropertyOperatorType.AND and has_negation_clause and has_primary_clase:
            # this negation is valid, since all conditions are met.
            # So, we don't need to pair this with anything in the rest of the tree
            # return no negations, and yes to primary clauses
            return False, True

    return has_negation_clause, has_primary_clase


class EnterpriseCohortQuery(FOSSCohortQuery):
    def get_query(self) -> tuple[str, dict[str, Any]]:
        if not self._outer_property_groups:
            # everything is pushed down, no behavioral stuff to do
            # thus, use personQuery directly
            return self._person_query.get_query(prepend=self._cohort_pk)

        # TODO: clean up this kludge. Right now, get_conditions has to run first so that _fields is populated for _get_behavioral_subquery()
        conditions, condition_params = self._get_conditions()
        self.params.update(condition_params)

        subq = []

        if self.sequence_filters_to_query:
            (
                sequence_query,
                sequence_params,
                sequence_query_alias,
            ) = self._get_sequence_query()
            subq.append((sequence_query, sequence_query_alias))
            self.params.update(sequence_params)
        else:
            (
                behavior_subquery,
                behavior_subquery_params,
                behavior_query_alias,
            ) = self._get_behavior_subquery()
            subq.append((behavior_subquery, behavior_query_alias))
            self.params.update(behavior_subquery_params)

        person_query, person_params, person_query_alias = self._get_persons_query(prepend=str(self._cohort_pk))
        subq.append((person_query, person_query_alias))
        self.params.update(person_params)

        # Since we can FULL OUTER JOIN, we may end up with pairs of uuids where one side is blank. Always try to choose the non blank ID
        q, fields = self._build_sources(subq)

        # optimize_aggregation_in_order slows down this query but massively decreases memory usage
        # this is fine for offline cohort calculation
        final_query = f"""
        SELECT {fields} AS id  FROM
        {q}
        WHERE 1 = 1
        {conditions}
        SETTINGS optimize_aggregation_in_order = 1, join_algorithm = 'auto'
        """

        return final_query, self.params

    def _get_condition_for_property(self, prop: Property, prepend: str, idx: int) -> tuple[str, dict[str, Any]]:
        res: str = ""
        params: dict[str, Any] = {}

        if prop.type == "behavioral":
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
        elif (
            prop.type == "static-cohort"
        ):  # "cohort" and "precalculated-cohort" are handled by flattening during initialization
            res, params = self.get_static_cohort_condition(prop, prepend, idx)
        elif prop.type == "dynamic-cohort":
            res, params = self.get_dynamic_cohort_condition(prop, prepend, idx)
        else:
            raise ValueError(f"Invalid property type for Cohort queries: {prop.type}")

        return res, params

    def get_stopped_performing_event(self, prop: Property, prepend: str, idx: int) -> tuple[str, dict[str, Any]]:
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
            f"{'NOT' if prop.negation else ''} coalesce({column_name}, false)",
            {
                f"{date_param}": date_value,
                f"{seq_date_param}": seq_date_value,
                **entity_params,
            },
        )

    def get_restarted_performing_event(self, prop: Property, prepend: str, idx: int) -> tuple[str, dict[str, Any]]:
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
            f"{'NOT' if prop.negation else ''} coalesce({column_name}, false)",
            {
                f"{date_param}": date_value,
                f"{seq_date_param}": seq_date_value,
                **entity_params,
            },
        )

    def get_performed_event_first_time(self, prop: Property, prepend: str, idx: int) -> tuple[str, dict[str, Any]]:
        event = (prop.event_type, prop.key)
        entity_query, entity_params = self._get_entity(event, prepend, idx)

        column_name = f"first_time_condition_{prepend}_{idx}"

        date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        date_param = f"{prepend}_date_{idx}"
        date_interval = validate_interval(prop.time_interval)

        self._restrict_event_query_by_time = False

        field = f"minIf(timestamp, {entity_query}) >= now() - INTERVAL %({date_param})s {date_interval} AND minIf(timestamp, {entity_query}) < now() as {column_name}"

        self._fields.append(field)

        return (
            f"{'NOT' if prop.negation else ''} coalesce({column_name}, false)",
            {f"{date_param}": date_value, **entity_params},
        )

    def get_performed_event_regularly(self, prop: Property, prepend: str, idx: int) -> tuple[str, dict[str, Any]]:
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

        return (
            f"{'NOT' if prop.negation else ''} coalesce({column_name}, false)",
            {**entity_params, **params},
        )

    @cached_property
    def sequence_filters_to_query(self) -> list[Property]:
        props = []
        for prop in self._filter.property_groups.flat:
            if prop.value == "performed_event_sequence":
                props.append(prop)
        return props

    @cached_property
    def sequence_filters_lookup(self) -> dict[str, str]:
        lookup = {}
        for idx, prop in enumerate(self.sequence_filters_to_query):
            lookup[str(prop.to_dict())] = f"{idx}"
        return lookup

    def _get_sequence_query(self) -> tuple[str, dict[str, Any], str]:
        params = {}

        materialized_columns = list(self._column_optimizer.event_columns_to_query)
        names = [
            "event",
            "properties",
            "distinct_id",
            "timestamp",
            *materialized_columns,
        ]

        person_prop_query = ""
        person_prop_params: dict = {}

        _inner_fields = [f"{self._person_id_alias} AS person_id"]
        _intermediate_fields = ["person_id"]
        _outer_fields = ["person_id"]

        _inner_fields.extend(names)
        _intermediate_fields.extend(names)

        for idx, prop in enumerate(self.sequence_filters_to_query):
            (
                step_cols,
                intermediate_cols,
                aggregate_cols,
                seq_params,
            ) = self._get_sequence_filter(prop, idx)
            _inner_fields.extend(step_cols)
            _intermediate_fields.extend(intermediate_cols)
            _outer_fields.extend(aggregate_cols)
            params.update(seq_params)

        date_condition, date_params = self._get_date_condition()
        params.update(date_params)

        event_param_name = f"{self._cohort_pk}_event_ids"

        if self.should_pushdown_persons and self._person_on_events_mode != PersonsOnEventsMode.DISABLED:
            person_prop_query, person_prop_params = self._get_prop_groups(
                self._inner_property_groups,
                person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS,
                person_id_joined_alias=self._person_id_alias,
            )

        new_query = f"""
        SELECT {", ".join(_inner_fields)} FROM events AS {self.EVENT_TABLE_ALIAS}
        {self._get_person_ids_query()}
        WHERE team_id = %(team_id)s
        AND event IN %({event_param_name})s
        {date_condition}
        {person_prop_query}
        """

        intermediate_query = f"""
        SELECT {", ".join(_intermediate_fields)} FROM ({new_query})
        """

        _outer_fields.extend(self._fields)

        outer_query = f"""
        SELECT {", ".join(_outer_fields)} FROM ({intermediate_query})
        GROUP BY person_id
        """
        return (
            outer_query,
            {
                "team_id": self._team_id,
                event_param_name: self._events,
                **params,
                **person_prop_params,
            },
            self.FUNNEL_QUERY_ALIAS,
        )

    def _get_sequence_filter(self, prop: Property, idx: int) -> tuple[list[str], list[str], list[str], dict[str, Any]]:
        event = validate_entity((prop.event_type, prop.key))
        entity_query, entity_params = self._get_entity(event, f"event_sequence_{self._cohort_pk}", idx)
        seq_event = validate_entity((prop.seq_event_type, prop.seq_event))

        seq_entity_query, seq_entity_params = self._get_entity(seq_event, f"seq_event_sequence_{self._cohort_pk}", idx)

        time_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        time_interval = validate_interval(prop.time_interval)
        seq_date_value = parse_and_validate_positive_integer(prop.seq_time_value, "time_value")
        seq_date_interval = validate_interval(prop.seq_time_interval)
        self._check_earliest_date((time_value, time_interval))

        event_prepend = f"event_{idx}"

        duplicate_event = 0
        if event == seq_event:
            duplicate_event = 1

        aggregate_cols = []
        aggregate_condition = f"{'NOT' if prop.negation else ''} max(if({entity_query} AND {event_prepend}_latest_0 < {event_prepend}_latest_1 AND {event_prepend}_latest_1 <= {event_prepend}_latest_0 + INTERVAL {seq_date_value} {seq_date_interval}, 2, 1)) = 2 AS {self.SEQUENCE_FIELD_ALIAS}_{self.sequence_filters_lookup[str(prop.to_dict())]}"
        aggregate_cols.append(aggregate_condition)

        condition_cols = []
        timestamp_condition = f"min({event_prepend}_latest_1) over (PARTITION by person_id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND {duplicate_event} PRECEDING) {event_prepend}_latest_1"
        condition_cols.append(f"{event_prepend}_latest_0")
        condition_cols.append(timestamp_condition)

        step_cols = []
        step_cols.append(
            f"if({entity_query} AND timestamp > now() - INTERVAL {time_value} {time_interval}, 1, 0) AS {event_prepend}_step_0"
        )
        step_cols.append(f"if({event_prepend}_step_0 = 1, timestamp, null) AS {event_prepend}_latest_0")

        step_cols.append(
            f"if({seq_entity_query} AND timestamp > now() - INTERVAL {time_value} {time_interval}, 1, 0) AS {event_prepend}_step_1"
        )
        step_cols.append(f"if({event_prepend}_step_1 = 1, timestamp, null) AS {event_prepend}_latest_1")

        return (
            step_cols,
            condition_cols,
            aggregate_cols,
            {
                **entity_params,
                **seq_entity_params,
            },
        )

    def get_performed_event_sequence(self, prop: Property, prepend: str, idx: int) -> tuple[str, dict[str, Any]]:
        return (
            f"{self.SEQUENCE_FIELD_ALIAS}_{self.sequence_filters_lookup[str(prop.to_dict())]}",
            {},
        )

    # Check if negations are always paired with a positive filter
    # raise a value error warning that this is an invalid cohort
    def _validate_negations(self) -> None:
        has_pending_negation, has_primary_clause = check_negation_clause(self._filter.property_groups)
        if has_pending_negation:
            raise ValueError("Negations must be paired with a positive filter.")
