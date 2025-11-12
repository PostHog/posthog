from collections import namedtuple
from numbers import Number
from typing import Literal, Optional, Union, cast

import posthoganalytics
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    ActorsQuery,
    BaseMathType,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    EventsQuery,
    FunnelConversionWindowTimeUnit,
    FunnelsActorsQuery,
    FunnelsFilter,
    FunnelsQuery,
    HogQLPropertyFilter,
    HogQLQueryModifiers,
    InsightActorsQuery,
    PersonPropertyFilter,
    PersonsOnEventsMode,
    PropertyGroupFilterValue,
    PropertyOperator,
    StickinessActorsQuery,
    StickinessCriteria,
    StickinessFilter,
    StickinessQuery,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery, SelectSetNode, SelectSetQuery
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.property import get_property_type
from posthog.hogql.query import HogQLQueryExecutor

from posthog.constants import PropertyOperatorType
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.models import Cohort, Filter, Property, Team
from posthog.models.property import PropertyGroup
from posthog.queries.cohort_query import CohortQuery
from posthog.queries.foss_cohort_query import (
    INTERVAL_TO_SECONDS,
    FOSSCohortQuery,
    parse_and_validate_positive_integer,
    validate_interval,
)
from posthog.types import AnyPropertyFilter


class TestWrapperCohortQuery(CohortQuery):
    def __init__(self, filter: Filter, team: Team):
        cohort_query = CohortQuery(filter=filter, team=team)
        executor = HogQLCohortQuery(cohort_query=cohort_query).get_query_executor()
        self.hogql_result = executor.execute()
        self.clickhouse_query = executor.clickhouse_sql
        super().__init__(filter=filter, team=team)


def convert_property(prop: Property) -> PersonPropertyFilter:
    value = prop.value
    if isinstance(value, Number):
        value = str(value)
    elif isinstance(value, list):
        value = [str(x) for x in value]
    return PersonPropertyFilter(key=prop.key, value=value, operator=prop.operator or PropertyOperator.EXACT)


def property_to_typed_property(property: Property) -> EventPropertyFilter | HogQLPropertyFilter:
    type = get_property_type(property)
    if type == "event":
        return EventPropertyFilter(**property.to_dict())
    if type == "hogql":
        return HogQLPropertyFilter(**property.to_dict())
    raise ValidationError("Property type not supported")


def convert(prop: PropertyGroup) -> PropertyGroupFilterValue:
    r = PropertyGroupFilterValue(
        type=prop.type,
        values=[convert(x) if isinstance(x, PropertyGroup) else convert_property(x) for x in prop.values],
    )
    return r


class HogQLCohortQuery:
    def __init__(
        self,
        cohort_query: Optional[CohortQuery] = None,
        cohort: Optional[Cohort] = None,
        team: Optional[Team] = None,
    ):
        if cohort is not None:
            self.hogql_context = HogQLContext(team_id=cohort.team.pk, enable_select_queries=True)
            self.team = team or cohort.team
            filter = FOSSCohortQuery.unwrap_cohort(
                Filter(
                    data={"properties": cohort.properties},
                    team=cohort.team,
                    hogql_context=self.hogql_context,
                ),
                self.team.pk,
            )
            self.property_groups = filter.property_groups
        elif cohort_query is not None:
            self.hogql_context = HogQLContext(team_id=cohort_query._team_id, enable_select_queries=True)
            self.property_groups = cohort_query._filter.property_groups
            self.team = team or cohort_query._team
        else:
            raise

    def get_query_executor(self) -> HogQLQueryExecutor:
        return HogQLQueryExecutor(
            query_type="HogQLCohortQuery",
            query=self.get_query(),
            modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
            team=self.team,
            limit_context=LimitContext.COHORT_CALCULATION,
            settings=HogQLGlobalSettings(allow_experimental_analyzer=None),
        )

    def get_query(self) -> SelectQuery | SelectSetQuery:
        return self._get_conditions()

    def query_str(self, dialect: Literal["hogql", "clickhouse"]):
        return prepare_and_print_ast(self.get_query(), self.hogql_context, dialect, pretty=True)[0]

    def _get_series(self, prop: Property, math=None):
        if prop.event_type == "events":
            return [EventsNode(event=prop.key, math=math)]
        elif prop.event_type == "actions":
            return [ActionsNode(id=int(prop.key), math=math)]
        else:
            raise ValueError(f"Event type must be 'events' or 'actions'")

    def _actors_query_from_source(
        self, source: Union[InsightActorsQuery, FunnelsActorsQuery, StickinessActorsQuery]
    ) -> ast.SelectQuery:
        actors_query = ActorsQuery(
            source=source,
            select=["id"],
        )
        return ActorsQueryRunner(team=self.team, query=actors_query).to_query()

    def get_performed_event_condition(self, prop: Property, first_time: bool = False) -> ast.SelectQuery:
        math = None
        if first_time:
            math = BaseMathType.FIRST_TIME_FOR_USER
        # either an action or an event
        series = self._get_series(prop, math)

        if prop.event_filters:
            filter = Filter(data={"properties": prop.event_filters}).property_groups
            series[0].properties = filter

        if prop.explicit_datetime:
            # Explicit datetime filter, can be a relative or absolute date, follows same convention
            # as all analytics datetime filters
            date_from = prop.explicit_datetime
        else:
            date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
            date_interval = validate_interval(prop.time_interval)
            date_from = f"-{date_value}{date_interval[:1]}"

        trends_query = TrendsQuery(
            dateRange=DateRange(date_from=date_from),
            trendsFilter=TrendsFilter(display="ActionsBarValue"),
            series=series,
        )

        return self._actors_query_from_source(InsightActorsQuery(source=trends_query))

    def get_performed_event_multiple(self, prop: Property) -> ast.SelectQuery:
        count = parse_and_validate_positive_integer(prop.operator_value, "operator_value")

        if prop.explicit_datetime:
            date_from = prop.explicit_datetime
        else:
            date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
            date_interval = validate_interval(prop.time_interval)
            date_from = f"-{date_value}{date_interval[:1]}"

        events_query = EventsQuery(after=date_from, select=["person_id", "count()"])
        if prop.event_type == "events":
            events_query.event = prop.key
        elif prop.event_type == "actions":
            events_query.actionId = int(prop.key)
        else:
            raise ValueError(f"Event type must be 'events' or 'actions'")

        if prop.operator == "gte":
            events_query.where = [f"count() >= {count}"]
        elif prop.operator == "lte":
            events_query.where = [f"count() <= {count}"]
        elif prop.operator == "gt":
            events_query.where = [f"count() > {count}"]
        elif prop.operator == "lt":
            events_query.where = [f"count() < {count}"]
        elif prop.operator == "eq" or prop.operator == "exact" or prop.operator is None:  # type: ignore[comparison-overlap]
            events_query.where = [f"count() = {count}"]
        else:
            raise ValidationError("count_operator must be gt(e), lt(e), exact, or None")

        if prop.event_filters:
            property_groups = Filter(data={"properties": prop.event_filters}).property_groups
            typed_properties: list[AnyPropertyFilter] = []
            for property in property_groups.values:
                if isinstance(property, PropertyGroup):
                    raise ValidationError("Property groups are not supported in this behavioral cohort type")
                typed_properties.append(property_to_typed_property(property))
            events_query.properties = typed_properties

        events_query_runner = EventsQueryRunner(team=self.team, query=events_query)
        return cast(
            ast.SelectQuery,
            parse_select("select person_id as id from {event_query}", {"event_query": events_query_runner.to_query()}),
        )

    def get_performed_event_sequence(self, prop: Property) -> ast.SelectQuery:
        # either an action or an event
        series: list[EventsNode | ActionsNode] = []
        assert prop.seq_event is not None

        if prop.event_type == "events":
            series.append(EventsNode(event=prop.key))
        elif prop.event_type == "actions":
            series.append(ActionsNode(id=int(prop.key)))
        else:
            raise ValueError(f"Event type must be 'events' or 'actions'")

        if prop.seq_event_type == "events":
            series.append(EventsNode(event=prop.seq_event))
        elif prop.seq_event_type == "actions":
            series.append(ActionsNode(id=int(prop.seq_event)))
        else:
            raise ValueError(f"Event type must be 'events' or 'actions'")

        if prop.explicit_datetime:
            date_from = prop.explicit_datetime
        else:
            date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
            date_interval = validate_interval(prop.time_interval)
            date_from = f"-{date_value}{date_interval[:1]}"

        date_value = parse_and_validate_positive_integer(prop.seq_time_value, "seq_time_value")
        date_interval = validate_interval(prop.seq_time_interval)
        funnelWindowInterval = date_value * INTERVAL_TO_SECONDS[date_interval]

        funnel_query = FunnelsQuery(
            series=series,
            dateRange=DateRange(date_from=date_from),
            funnelsFilter=FunnelsFilter(
                funnelWindowInterval=funnelWindowInterval,
                funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.SECOND,
            ),
        )
        return self._actors_query_from_source(FunnelsActorsQuery(source=funnel_query, funnelStep=2))

    def get_stopped_performing_event(self, prop: Property) -> ast.SelectSetQuery:
        # time_value / time_value_interval is the furthest back
        # seq_time_value / seq_time_interval is when they stopped it
        select_for_full_range = self.get_performed_event_condition(prop)

        new_props = prop.to_dict()
        new_props.update({"time_value": prop.seq_time_value, "time_interval": prop.seq_time_interval})
        select_for_recent_range = self.get_performed_event_condition(Property(**new_props))
        return ast.SelectSetQuery(
            initial_select_query=select_for_full_range,
            subsequent_select_queries=[SelectSetNode(set_operator="EXCEPT", select_query=select_for_recent_range)],
        )

    def get_restarted_performing_event(self, prop: Property) -> ast.SelectSetQuery:
        # time_value / time_value_interval is the furthest back
        # seq_time_value / seq_time_interval is when they stopped it
        series = self._get_series(prop)
        first_time_series = self._get_series(prop, math=BaseMathType.FIRST_TIME_FOR_USER)
        date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        date_interval = validate_interval(prop.time_interval)
        date_from = f"-{date_value}{date_interval[:1]}"

        date_value = parse_and_validate_positive_integer(prop.seq_time_value, "seq_time_value")
        date_interval = validate_interval(prop.seq_time_interval)
        date_to = f"-{date_value}{date_interval[:1]}"

        select_for_first_range = self._actors_query_from_source(
            InsightActorsQuery(
                source=TrendsQuery(
                    dateRange=DateRange(date_from=date_from, date_to=date_to),
                    trendsFilter=TrendsFilter(display="ActionsBarValue"),
                    series=series,
                )
            )
        )

        # want people in here who were not "for the first time" who were not in the prior one
        select_for_second_range = self._actors_query_from_source(
            InsightActorsQuery(
                source=TrendsQuery(
                    dateRange=DateRange(date_from=date_to),
                    trendsFilter=TrendsFilter(display="ActionsBarValue"),
                    series=series,
                )
            )
        )

        select_for_second_range_first_time = self._actors_query_from_source(
            InsightActorsQuery(
                source=TrendsQuery(
                    dateRange=DateRange(date_from=date_to),
                    trendsFilter=TrendsFilter(display="ActionsBarValue"),
                    series=first_time_series,
                )
            )
        )

        # People who did the event in the recent window, who had done it previously, who did not do it in the previous window
        return ast.SelectSetQuery(
            initial_select_query=select_for_second_range,
            subsequent_select_queries=[
                SelectSetNode(set_operator="EXCEPT", select_query=select_for_second_range_first_time),
                SelectSetNode(set_operator="EXCEPT", select_query=select_for_first_range),
            ],
        )

    def get_performed_event_regularly(self, prop: Property) -> ast.SelectQuery:
        # "operator_value": 1, "time_value": 2, "time_interval": "day", "min_periods": 3, "total_periods": 4
        # event [operator: exactly, at least, at most] [operator_value: int] times per [time_value: int] [time_interval: days, weeks, months, years] period
        # for at least [min_periods: int] of the last [total_periods: int] periods

        # min_periods
        # operator (gte)
        # operator_value (int)
        # time_interval
        # time_value
        # total periods

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

        series = self._get_series(prop)

        # Remove when we support years
        if date_interval == "year":
            date_interval = "month"
            time_value = time_value * 12

        date_from = f"-{time_value * total_period_count}{date_interval[:1]}"

        stickiness_query = StickinessQuery(
            series=series,
            dateRange=DateRange(date_from=date_from, date_to="-1d"),
            interval=date_interval,
            intervalCount=time_value,
            stickinessFilter=StickinessFilter(
                stickinessCriteria=StickinessCriteria(operator=prop.operator, value=operator_value)
            ),
        )
        return self._actors_query_from_source(
            StickinessActorsQuery(source=stickiness_query, day=min_period_count, operator="gte")
        )

    def get_person_condition(self, prop: Property) -> ast.SelectQuery:
        # key = $sample_field
        # type = "person"
        # value = test@posthog.com
        actors_query = ActorsQuery(
            properties=[
                PersonPropertyFilter(key=prop.key, value=prop.value, operator=prop.operator or PropertyOperator.EXACT)
            ],
            select=["id"],
        )
        query_runner = ActorsQueryRunner(team=self.team, query=actors_query)
        return query_runner.to_query()

    def get_static_cohort_condition(self, prop: Property) -> ast.SelectQuery:
        cohort = Cohort.objects.get(pk=cast(int, prop.value))
        return cast(
            ast.SelectQuery,
            parse_select(
                f"SELECT person_id as id FROM static_cohort_people WHERE cohort_id = {cohort.pk} AND team_id = {self.team.pk}",
            ),
        )

    def get_dynamic_cohort_condition(self, prop: Property) -> ast.SelectQuery:
        cohort_id = cast(int, prop.value)

        return cast(
            ast.SelectQuery,
            parse_select(
                f"""
                SELECT person_id as id FROM cohort_people
                WHERE cohort_id = {cohort_id}
                AND team_id = {self.team.pk}
                """,
            ),
        )

    def _get_condition_for_property(self, prop: Property) -> ast.SelectQuery | ast.SelectSetQuery:
        if prop.type == "behavioral":
            if prop.value == "performed_event":
                return self.get_performed_event_condition(prop)
            elif prop.value == "performed_event_first_time":
                return self.get_performed_event_condition(prop, True)
            elif prop.value == "performed_event_multiple":
                return self.get_performed_event_multiple(prop)
            elif prop.value == "performed_event_sequence":
                return self.get_performed_event_sequence(prop)
            elif prop.value == "stopped_performing_event":
                return self.get_stopped_performing_event(prop)
            elif prop.value == "restarted_performing_event":
                return self.get_restarted_performing_event(prop)
            elif prop.value == "performed_event_regularly":
                return self.get_performed_event_regularly(prop)
            else:
                raise ValueError(f"Invalid behavioral property value for Cohort: {prop.value}")
        elif prop.type == "person":
            return self.get_person_condition(prop)
        elif prop.type == "static-cohort":  # static cohorts are handled by flattening during initialization
            return self.get_static_cohort_condition(prop)
        elif prop.type == "dynamic-cohort":
            return self.get_dynamic_cohort_condition(prop)
        else:
            raise ValueError(f"Invalid property type for Cohort queries: {prop.type}")

    def _should_combine_person_properties(self) -> bool:
        return posthoganalytics.feature_enabled(
            "hogql-cohort-combine-person-properties",
            str(self.team.uuid),
            groups={
                "organization": str(self.team.organization_id),
                "project": str(self.team.id),
            },
            group_properties={
                "organization": {
                    "id": str(self.team.organization_id),
                },
                "project": {
                    "id": str(self.team.id),
                },
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    def _get_conditions(self) -> ast.SelectQuery | ast.SelectSetQuery:
        Condition = namedtuple("Condition", ["query", "negation"])
        should_combine_person_properties = self._should_combine_person_properties()

        def unwrap_property(prop: Union[PropertyGroup, Property]) -> Optional[Property]:
            """Unwrap a PropertyGroup to get the underlying Property if it contains exactly one."""
            if isinstance(prop, Property):
                return prop
            if isinstance(prop, PropertyGroup) and len(prop.values) == 1:
                return unwrap_property(prop.values[0])
            return None

        def can_combine_person_properties(properties: Union[list[PropertyGroup], list[Property]]) -> bool:
            """Check if all properties are person properties that can be combined into a single query."""
            if not properties:
                return False
            unwrapped = [unwrap_property(prop) for prop in properties]
            return all(p is not None and p.type == "person" and not p.negation for p in unwrapped)

        def combine_person_properties(properties: Union[list[Property], list[PropertyGroup]]) -> ast.SelectQuery:
            """
            Combine multiple person property filters into a single ActorsQuery.

            This optimization replaces N separate queries with N-1 INTERSECT operations
            with a single query that includes all conditions. For cohorts with many person
            properties, this reduces query time by ~19x and memory usage by ~15x.

            Example:
                Before: Query1 INTERSECT DISTINCT Query2 INTERSECT DISTINCT Query3
                After:  Single query with AND(condition1, condition2, condition3)
            """
            person_filters = []
            for prop_or_group in properties:
                # Unwrap PropertyGroup to get the underlying Property
                prop = unwrap_property(prop_or_group)
                if prop is None:
                    continue
                person_filters.append(convert_property(prop))

            actors_query = ActorsQuery(
                properties=person_filters,
                select=["id"],
            )
            query_runner = ActorsQueryRunner(team=self.team, query=actors_query)
            return query_runner.to_query()

        def build_conditions(
            prop: Optional[Union[PropertyGroup, Property]],
        ) -> Condition:
            if not prop:
                raise ValidationError("Cohort has a null property", str(prop))

            if isinstance(prop, Property):
                return Condition(self._get_condition_for_property(prop), prop.negation or False)

            if should_combine_person_properties:
                if prop.type == PropertyOperatorType.AND and can_combine_person_properties(prop.values):
                    return Condition(combine_person_properties(prop.values), False)

            children = [build_conditions(property) for property in prop.values]

            if len(children) == 0:
                raise ValidationError("Cohort has a property group with no condition", str(prop))

            all_children_negated = all(condition.negation for condition in children)
            all_children_positive = all(not condition.negation for condition in children)

            parent_condition_negated = all_children_negated

            if prop.type == PropertyOperatorType.OR:
                if all_children_positive or all_children_negated:
                    return Condition(
                        ast.SelectSetQuery(
                            initial_select_query=children[0][0],
                            subsequent_select_queries=[
                                SelectSetNode(
                                    select_query=query,
                                    set_operator="UNION DISTINCT" if all_children_positive else "INTERSECT DISTINCT",
                                )
                                for (query, negation) in children[1:]
                            ],
                        ),
                        parent_condition_negated,
                    )
                else:
                    # Use De Morgan's law to convert OR to AND
                    parent_condition_negated = True
                    children = [Condition(query, not negation) for query, negation in children]

            # Negation criteria must be accompanied by at least one positive matching criteria.
            # Sort the positive queries first, then subtract the negative queries.
            children.sort(key=lambda query: query[1])  # False before True
            return Condition(
                ast.SelectSetQuery(
                    initial_select_query=children[0][0],
                    subsequent_select_queries=[
                        SelectSetNode(
                            select_query=query,
                            set_operator=(
                                "UNION DISTINCT"
                                if all_children_negated
                                else ("EXCEPT" if negation else "INTERSECT DISTINCT")
                            ),
                        )
                        for (query, negation) in children[1:]
                    ],
                ),
                parent_condition_negated,
            )

        condition = build_conditions(self.property_groups)
        if condition.negation:
            raise ValidationError("Top level condition cannot be negated", str(self.property_groups))
        return condition.query
