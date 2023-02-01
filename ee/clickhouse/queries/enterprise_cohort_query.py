from typing import Any, Dict, List, Tuple, cast

from posthog.clickhouse.query_fragment import Param, QueryFragment, QueryFragmentLike, UniqueName
from posthog.constants import PropertyOperatorType
from posthog.models.cohort.util import get_count_operator
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property.property import Property, PropertyGroup
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.foss_cohort_query import (
    FOSSCohortQuery,
    parse_and_validate_positive_integer,
    validate_entity,
    validate_interval,
    validate_seq_date_more_recent_than_date,
)


def check_negation_clause(prop: PropertyGroup) -> Tuple[bool, bool]:
    has_negation_clause = False
    has_primary_clase = False
    if len(prop.values):
        if isinstance(prop.values[0], PropertyGroup):
            for p in cast(List[PropertyGroup], prop.values):
                has_neg, has_primary = check_negation_clause(p)
                has_negation_clause = has_negation_clause or has_neg
                has_primary_clase = has_primary_clase or has_primary

        else:
            for property in cast(List[Property], prop.values):
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
    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        if not self._outer_property_groups:
            # everything is pushed down, no behavioral stuff to do
            # thus, use personQuery directly
            return self._person_query.get_query(prepend=self._cohort_pk)

        # TODO: clean up this kludge. Right now, get_conditions has to run first so that _fields is populated for _get_behavioral_subquery()
        conditions = self._get_conditions()

        # Since we can FULL OUTER JOIN, we may end up with pairs of uuids where one side is blank. Always try to choose the non blank ID
        q, fields = self._build_sources(
            [
                (
                    self._get_sequence_query() if self.sequence_filters_to_query else self._get_behavior_subquery(),
                    self.FUNNEL_QUERY_ALIAS,
                ),
                (self._get_persons_query(prepend=str(self._cohort_pk)), self.PERSON_TABLE_ALIAS),
            ]
        )

        final_query = QueryFragment(
            """
            SELECT {fields} AS id
            FROM {q}
            WHERE 1 = 1
            {conditions}
            """,
            fields=fields,
            q=q,
            conditions=conditions,
        )

        return final_query.sql, final_query.query_params

    def _get_condition_for_property(self, prop: Property, prepend: str, idx: int) -> QueryFragment:
        if prop.type == "behavioral":
            if prop.value == "performed_event":
                return self.get_performed_event_condition(prop, prepend, idx)
            elif prop.value == "performed_event_multiple":
                return self.get_performed_event_multiple(prop, prepend, idx)
            elif prop.value == "stopped_performing_event":
                return self.get_stopped_performing_event(prop, prepend, idx)
            elif prop.value == "restarted_performing_event":
                return self.get_restarted_performing_event(prop, prepend, idx)
            elif prop.value == "performed_event_first_time":
                return self.get_performed_event_first_time(prop, prepend, idx)
            elif prop.value == "performed_event_sequence":
                return self.get_performed_event_sequence(prop, prepend, idx)
            elif prop.value == "performed_event_regularly":
                return self.get_performed_event_regularly(prop, prepend, idx)
        elif prop.type == "person":
            return self.get_person_condition(prop, prepend, idx)
        elif (
            prop.type == "static-cohort"
        ):  # "cohort" and "precalculated-cohort" are handled by flattening during initialization
            return self.get_static_cohort_condition(prop, prepend, idx)
        else:
            raise ValueError(f"Invalid property type for Cohort queries: {prop.type}")

        return QueryFragment("")

    def get_stopped_performing_event(self, prop: Property, prepend: str, idx: int) -> QueryFragment:
        event = (prop.event_type, prop.key)
        column_name = f"stopped_event_condition_{prepend}_{idx}"

        entity_query = self._get_entity(event, prepend, idx)
        date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        date_param = f"{prepend}_date_{idx}"
        date_interval = validate_interval(prop.time_interval)

        seq_date_value = parse_and_validate_positive_integer(prop.seq_time_value, "time_value")
        seq_date_param = f"{prepend}_seq_date_{idx}"
        seq_date_interval = validate_interval(prop.seq_time_interval)

        validate_seq_date_more_recent_than_date((seq_date_value, seq_date_interval), (date_value, date_interval))

        self._check_earliest_date((date_value, date_interval))

        # The user was doing the event in this time period
        event_was_happening_period = f"countIf(timestamp > now() - INTERVAL %({date_param})s {date_interval} AND timestamp <= now() - INTERVAL %({seq_date_param})s {seq_date_interval} AND {entity_query.sql})"
        # Then stopped in this time period
        event_stopped_period = f"countIf(timestamp > now() - INTERVAL %({seq_date_param})s {seq_date_interval} AND timestamp <= now() AND {entity_query.sql})"

        full_condition = QueryFragment(
            f"({event_was_happening_period} > 0 AND {event_stopped_period} = 0) as {column_name}",
            {f"{date_param}": Param(date_value), f"{seq_date_param}": Param(seq_date_value), **entity_query.params},
        )

        self._fields.append(full_condition)

        return QueryFragment(f"{'NOT' if prop.negation else ''} {column_name}")

    def get_restarted_performing_event(self, prop: Property, prepend: str, idx: int) -> QueryFragment:
        event = (prop.event_type, prop.key)
        column_name = f"restarted_event_condition_{prepend}_{idx}"

        entity_query = self._get_entity(event, prepend, idx)
        date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        date_param = f"{prepend}_date_{idx}"
        date_interval = validate_interval(prop.time_interval)

        seq_date_value = parse_and_validate_positive_integer(prop.seq_time_value, "time_value")
        seq_date_param = f"{prepend}_seq_date_{idx}"
        seq_date_interval = validate_interval(prop.seq_time_interval)

        validate_seq_date_more_recent_than_date((seq_date_value, seq_date_interval), (date_value, date_interval))

        self._restrict_event_query_by_time = False

        # Events should have been fired in the initial_period
        initial_period = (
            f"countIf(timestamp <= now() - INTERVAL %({date_param})s {date_interval} AND {entity_query.sql})"
        )
        # Then stopped in the event_stopped_period
        event_stopped_period = f"countIf(timestamp > now() - INTERVAL %({date_param})s {date_interval} AND timestamp <= now() - INTERVAL %({seq_date_param})s {seq_date_interval} AND {entity_query.sql})"
        # Then restarted in the final event_restart_period
        event_restarted_period = f"countIf(timestamp > now() - INTERVAL %({seq_date_param})s {seq_date_interval} AND timestamp <= now() AND {entity_query.sql})"

        # :KLUDGE: Since above code is not properly using QueryFragments, put it all together here.
        full_condition = QueryFragment(
            f"({initial_period} > 0 AND {event_stopped_period} = 0 AND {event_restarted_period} > 0) as {column_name}",
            {f"{date_param}": Param(date_value), f"{seq_date_param}": Param(seq_date_value), **entity_query.params},
        )

        self._fields.append(full_condition)

        return QueryFragment(f"{'NOT' if prop.negation else ''} {column_name}")

    def get_performed_event_first_time(self, prop: Property, prepend: str, idx: int) -> QueryFragment:
        event = (prop.event_type, prop.key)
        entity_query = self._get_entity(event, prepend, idx)

        column_name = f"first_time_condition_{prepend}_{idx}"

        date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        date_interval = validate_interval(prop.time_interval)

        self._restrict_event_query_by_time = False

        field = QueryFragment(
            "minIf(timestamp, {entity_query}) >= now() - INTERVAL %(__date)s {date_interval} AND minIf(timestamp, {entity_query}) < now() as {column_name}",
            {
                UniqueName("__date"): Param(date_value),
                "entity_query": entity_query,
                "date_interval": QueryFragment(date_interval),
                "column_name": QueryFragment(column_name),
            },
        )

        self._fields.append(field)

        return QueryFragment(f"{'NOT' if prop.negation else ''} {column_name}")

    def get_performed_event_regularly(self, prop: Property, prepend: str, idx: int) -> QueryFragment:
        event = (prop.event_type, prop.key)
        entity_query = self._get_entity(event, prepend, idx)

        column_name = f"performed_event_regularly_{prepend}_{idx}"

        date_interval = validate_interval(prop.time_interval)

        time_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        operator_value = parse_and_validate_positive_integer(prop.operator_value, "operator_value")
        min_period_count = parse_and_validate_positive_integer(prop.min_periods, "min_periods")
        total_period_count = parse_and_validate_positive_integer(prop.total_periods, "total_periods")

        if min_period_count > total_period_count:
            raise (
                ValueError(
                    f"min_periods ({min_period_count}) cannot be greater than total_periods ({total_period_count})"
                )
            )

        periods = []

        if total_period_count:
            for period in range(total_period_count):
                # Clause that returns 1 if the event was performed the expected number of times in the given time interval, otherwise 0
                periods.append(
                    QueryFragment(
                        """
                        if(
                            countIf(
                                {entity_query} and timestamp <= now() - INTERVAL %(__time_value)s * {period} {date_interval}
                                AND timestamp > now() - INTERVAL %(__time_value)s * ({period} + 1) {date_interval}
                            ) {operator} %(__operator_value)s,
                            1,
                            0
                        )
                        """,
                        {
                            UniqueName("__operator_value"): Param(operator_value),
                            UniqueName("__time_value"): Param(time_value),
                            "entity_query": entity_query,
                            "date_interval": QueryFragment(date_interval),
                            "operator": QueryFragment(get_count_operator(prop.operator)),
                            "period": QueryFragment(str(period)),
                        },
                    )
                )
        earliest_date = (total_period_count * time_value, date_interval)
        self._check_earliest_date(earliest_date)

        field = QueryFragment(
            "{expr} >= %(__min_periods)s AS {column_name}",
            {
                UniqueName("__min_periods"): Param(min_period_count),
                "expr": QueryFragment.join("+", periods),
                "column_name": QueryFragment(column_name),
            },
        )

        self._fields.append(field)

        return QueryFragment(f"{'NOT' if prop.negation else ''} {column_name}")

    @cached_property
    def sequence_filters_to_query(self) -> List[Property]:
        props = []
        for prop in self._filter.property_groups.flat:
            if prop.value == "performed_event_sequence":
                props.append(prop)
        return props

    @cached_property
    def sequence_filters_lookup(self) -> Dict[str, str]:
        lookup = {}
        for idx, prop in enumerate(self.sequence_filters_to_query):
            lookup[str(prop.to_dict())] = f"{idx}"
        return lookup

    def _get_sequence_query(self) -> QueryFragment:
        names = ["event", "properties", "distinct_id", "timestamp"]
        _inner_fields: List[QueryFragmentLike] = [
            f"{self.DISTINCT_ID_TABLE_ALIAS if not self._using_person_on_events else self.EVENT_TABLE_ALIAS}.person_id AS person_id",
            *names,
        ]
        _intermediate_fields: List[QueryFragmentLike] = ["person_id", *names]
        _outer_fields: List[QueryFragmentLike] = ["person_id"]

        for idx, prop in enumerate(self.sequence_filters_to_query):
            step_cols, intermediate_cols, aggregate_cols = self._get_sequence_filter(prop, idx)
            _inner_fields.extend(step_cols)
            _intermediate_fields.extend(intermediate_cols)
            _outer_fields.extend(aggregate_cols)

        date_condition = self._get_date_condition()

        if self.should_pushdown_persons and self._using_person_on_events:
            person_prop_query = QueryFragment.from_tuple(
                self._get_prop_groups(
                    self._inner_property_groups,
                    person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS,
                    person_id_joined_alias=f"{self.EVENT_TABLE_ALIAS}.person_id",
                )
            )
        else:
            person_prop_query = QueryFragment("")

        new_query = QueryFragment(
            """
            SELECT {fields}
            FROM events AS {alias}
            {distinct_id_query}
            WHERE team_id = %(team_id)s
            AND event IN %(__event_ids)s
            {date_condition}
            {person_prop_query}
            """,
            {
                "team_id": Param(self._team_id),
                UniqueName("__event_ids"): Param(self._events),
                "fields": QueryFragment.join(", ", _inner_fields),
                "alias": QueryFragment(self.EVENT_TABLE_ALIAS),
                "distinct_id_query": QueryFragment(self._get_distinct_id_query()),
                "date_condition": date_condition,
                "person_prop_query": person_prop_query,
            },
        )

        return QueryFragment(
            """
            SELECT {outer_fields}
            FROM (
                SELECT {intermediate_fields}
                FROM ({new_query})
            )
            GROUP BY person_id
            """,
            outer_fields=QueryFragment.join(", ", _outer_fields + self._fields),
            intermediate_fields=QueryFragment.join(", ", _intermediate_fields),
            new_query=new_query,
        )

    def _get_sequence_filter(
        self, prop: Property, idx: int
    ) -> Tuple[List[QueryFragmentLike], List[QueryFragmentLike], List[QueryFragmentLike]]:
        event = validate_entity((prop.event_type, prop.key))
        entity_query = self._get_entity(event, f"event_sequence_{self._cohort_pk}", idx)
        seq_event = validate_entity((prop.seq_event_type, prop.seq_event))

        seq_entity_query = self._get_entity(seq_event, f"seq_event_sequence_{self._cohort_pk}", idx)

        time_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        time_interval = validate_interval(prop.time_interval)
        seq_date_value = parse_and_validate_positive_integer(prop.seq_time_value, "time_value")
        seq_date_interval = validate_interval(prop.seq_time_interval)
        self._check_earliest_date((time_value, time_interval))

        event_prepend = f"event_{idx}"

        duplicate_event = 0
        if event == seq_event:
            duplicate_event = 1

        aggregate_cols: List[QueryFragmentLike] = [
            QueryFragment(
                """
                {negation} max(
                    if({entity_query} AND {event_prepend}_latest_0 < {event_prepend}_latest_1 AND {event_prepend}_latest_1 <= {event_prepend}_latest_0 + INTERVAL {seq_date_value} {seq_date_interval}, 2, 1)
                ) = 2 AS {alias}
                """,
                negation=QueryFragment("NOT" if prop.negation else ""),
                entity_query=entity_query,
                event_prepend=QueryFragment(event_prepend),
                seq_date_value=QueryFragment(str(seq_date_value)),
                seq_date_interval=QueryFragment(seq_date_interval),
                alias=QueryFragment(f"{self.SEQUENCE_FIELD_ALIAS}_{self.sequence_filters_lookup[str(prop.to_dict())]}"),
            )
        ]

        condition_cols: List[QueryFragmentLike] = [
            f"{event_prepend}_latest_0",
            f"min({event_prepend}_latest_1) over (PARTITION by person_id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND {duplicate_event} PRECEDING) {event_prepend}_latest_1",
        ]

        step_cols: List[QueryFragmentLike] = [
            QueryFragment(
                "if({entity_query} AND timestamp > now() - INTERVAL {time_value} {time_interval}, 1, 0) AS {event_prepend}_step_0",
                entity_query=entity_query,
                time_value=QueryFragment(str(time_value)),
                time_interval=QueryFragment(time_interval),
                event_prepend=QueryFragment(event_prepend),
            ),
            f"if({event_prepend}_step_0 = 1, timestamp, null) AS {event_prepend}_latest_0",
            QueryFragment(
                "if({seq_entity_query} AND timestamp > now() - INTERVAL {time_value} {time_interval}, 1, 0) AS {event_prepend}_step_1",
                seq_entity_query=seq_entity_query,
                time_value=QueryFragment(str(time_value)),
                time_interval=QueryFragment(time_interval),
                event_prepend=QueryFragment(event_prepend),
            ),
            f"if({event_prepend}_step_1 = 1, timestamp, null) AS {event_prepend}_latest_1",
        ]

        return step_cols, condition_cols, aggregate_cols

    def get_performed_event_sequence(self, prop: Property, prepend: str, idx: int) -> QueryFragment:
        return QueryFragment(f"{self.SEQUENCE_FIELD_ALIAS}_{self.sequence_filters_lookup[str(prop.to_dict())]}")

    # Check if negations are always paired with a positive filter
    # raise a value error warning that this is an invalid cohort
    def _validate_negations(self) -> None:
        has_pending_negation, has_primary_clause = check_negation_clause(self._filter.property_groups)
        if has_pending_negation:
            raise ValueError("Negations must be paired with a positive filter.")
