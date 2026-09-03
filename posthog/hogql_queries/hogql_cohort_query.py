from collections import namedtuple
from numbers import Number
from typing import Any, Literal, Optional, Union, cast

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
    PersonMetadataPropertyFilter,
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
from posthog.models import Filter, Property, Team, User
from posthog.models.property import OperatorInterval, PropertyGroup
from posthog.ph_client import feature_enabled_or_false
from posthog.types import AnyPropertyFilter

from products.cohorts.backend.models.cohort import Cohort

INTERVAL_TO_SECONDS = {
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,
    "year": 31536000,
}


def validate_interval(interval: Optional[OperatorInterval]) -> OperatorInterval:
    if interval is None or interval not in INTERVAL_TO_SECONDS.keys():
        raise ValueError(f"Invalid interval: {interval}")
    else:
        return interval


def parse_and_validate_positive_integer(value: Optional[Union[str, int]], value_name: str) -> int:
    if value is None:
        raise ValueError(f"{value_name} cannot be None")
    try:
        parsed_value = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"{value_name} must be an integer, got {value}")
    if parsed_value <= 0:
        raise ValueError(f"{value_name} must be greater than 0, got {value}")
    return parsed_value


def _require_select_query(query: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery:
    # A constant `select=["id"]` actors query never yields a set query. Fail loudly rather than
    # via a strippable assert if that invariant ever breaks.
    if not isinstance(query, ast.SelectQuery):
        raise ValueError("Expected a single SELECT query from the actors query, got a set query")
    return query


def unwrap_cohort(filter: Filter, team_id: int, team: Optional[Team] = None, cohort: Optional[Cohort] = None) -> Filter:
    """Flatten cohort-typed properties into nested static/dynamic-cohort PropertyGroups.

    Each ``cohort``/``precalculated-cohort`` property is replaced by an AND group holding a
    single ``static-cohort``/``dynamic-cohort`` property, while sibling properties are wrapped
    into AND groups too, propagating negation per De Morgan's law.
    """

    def _unwrap(property_group: PropertyGroup, negate_group: bool = False) -> PropertyGroup:
        nonlocal team
        if len(property_group.values):
            if isinstance(property_group.values[0], PropertyGroup):
                # dealing with a list of property groups, so unwrap each one
                # Propogate the negation to the children and handle as necessary with respect to deMorgan's law
                if not negate_group:
                    return PropertyGroup(
                        type=property_group.type,
                        values=[_unwrap(v) for v in cast(list[PropertyGroup], property_group.values)],
                    )
                else:
                    return PropertyGroup(
                        type=(
                            PropertyOperatorType.AND
                            if property_group.type == PropertyOperatorType.OR
                            else PropertyOperatorType.OR
                        ),
                        values=[_unwrap(v, True) for v in cast(list[PropertyGroup], property_group.values)],
                    )

            elif isinstance(property_group.values[0], Property):
                # dealing with a list of properties
                # if any single one is a cohort property, unwrap it into a property group
                # which implies converting everything else in the list into a property group too

                new_property_group_list: list[PropertyGroup] = []
                for prop in property_group.values:
                    prop = cast(Property, prop)
                    current_negation = prop.negation or False
                    negation_value = not current_negation if negate_group else current_negation
                    if prop.type in ["cohort", "precalculated-cohort"]:
                        try:
                            # Use passed cohort object if it matches the requested cohort ID
                            if cohort is not None and str(cohort.pk) == str(prop.value):
                                prop_cohort = cohort
                            else:
                                # Use passed team object if available, otherwise fetch from database
                                if team is None:
                                    team = Team.objects.get(pk=team_id)
                                prop_cohort = Cohort.objects.get(
                                    pk=cast(str | int, prop.value), team__project_id=team.project_id
                                )
                            new_property_group_list.append(
                                PropertyGroup(
                                    type=PropertyOperatorType.AND,
                                    values=[
                                        Property(
                                            type="static-cohort" if prop_cohort.is_static else "dynamic-cohort",
                                            key="id",
                                            value=prop_cohort.pk,
                                            negation=negation_value,
                                        )
                                    ],
                                )
                            )
                        except Cohort.DoesNotExist:
                            new_property_group_list.append(
                                PropertyGroup(
                                    type=PropertyOperatorType.AND,
                                    values=[
                                        Property(
                                            key="fake_key_01r2ho",
                                            value="0",
                                            type="person",
                                        )
                                    ],
                                )
                            )
                    else:
                        prop.negation = negation_value
                        new_property_group_list.append(PropertyGroup(type=PropertyOperatorType.AND, values=[prop]))
                if not negate_group:
                    return PropertyGroup(type=property_group.type, values=new_property_group_list)
                else:
                    return PropertyGroup(
                        type=(
                            PropertyOperatorType.AND
                            if property_group.type == PropertyOperatorType.OR
                            else PropertyOperatorType.OR
                        ),
                        values=new_property_group_list,
                    )

        return property_group

    new_props = _unwrap(filter.property_groups)
    return filter.shallow_clone({"properties": new_props.to_dict()})


class TestWrapperCohortQuery:
    """Runs a filter through HogQLCohortQuery for the cohort-query test suite.

    ``hogql_result`` holds the executed result the tests assert membership against;
    ``clickhouse_query`` / ``get_query`` expose the generated SQL.
    """

    def __init__(self, filter: Filter, team: Team):
        executor = HogQLCohortQuery(filter=filter, team=team).get_query_executor()
        self.hogql_result = executor.execute()
        self.clickhouse_query = executor.clickhouse_sql

    def get_query(self) -> tuple[str, dict[str, Any]]:
        return self.clickhouse_query or "", {}


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


def _person_test_account_properties(team: Team) -> list[Property]:
    """Person-property filters from team.test_account_filters.

    Event/element/hogql-scoped test filters can't be standalone cohort conditions, and
    cohort-typed ones are excluded here to avoid self-referential cohorts (a team test
    filter can point at the very cohort being calculated).
    """
    return [
        Property(**prop)
        for prop in (team.test_account_filters or [])
        if isinstance(prop, dict) and prop.get("type") == "person"
    ]


class HogQLCohortQuery:
    def __init__(
        self,
        filter: Optional[Filter] = None,
        cohort: Optional[Cohort] = None,
        team: Optional[Team] = None,
    ):
        if cohort is not None:
            self.hogql_context = HogQLContext(team_id=cohort.team.pk, enable_select_queries=True)
            self.team = team or cohort.team
            unwrapped = unwrap_cohort(
                Filter(
                    data={"properties": cohort.properties},
                    team=cohort.team,
                    hogql_context=self.hogql_context,
                ),
                self.team.pk,
                self.team,
                cohort,
            )
            property_groups = unwrapped.property_groups
            if (cohort.filters or {}).get("filterTestAccounts"):
                test_props = _person_test_account_properties(self.team)
                if test_props:
                    property_groups = PropertyGroup(
                        type=PropertyOperatorType.AND,
                        values=[
                            property_groups,
                            PropertyGroup(type=PropertyOperatorType.AND, values=test_props),
                        ],
                    )
            self.property_groups = property_groups
        elif filter is not None:
            if team is None:
                raise ValueError("HogQLCohortQuery requires a team when constructed from a filter")
            self.hogql_context = HogQLContext(team_id=team.pk, enable_select_queries=True)
            self.team = team
            self.property_groups = unwrap_cohort(filter, team.pk, team).property_groups
        else:
            raise ValueError("HogQLCohortQuery requires either a cohort or a filter")

    def get_query_executor(
        self, *, user: Optional[User] = None, bypass_warehouse_access_control: bool = False
    ) -> HogQLQueryExecutor:
        return HogQLQueryExecutor(
            query_type="HogQLCohortQuery",
            query=self.get_query(),
            modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
            team=self.team,
            limit_context=LimitContext.COHORT_CALCULATION,
            settings=HogQLGlobalSettings(),
            user=user,
            bypass_warehouse_access_control=bypass_warehouse_access_control,
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
        return _require_select_query(ActorsQueryRunner(team=self.team, query=actors_query).to_query())

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
            date_to = prop.explicit_datetime_to
        else:
            date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
            date_interval = validate_interval(prop.time_interval)
            date_from = f"-{date_value}{date_interval[:1]}"
            date_to = None

        trends_query = TrendsQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            trendsFilter=TrendsFilter(display="ActionsBarValue"),
            series=series,
        )

        return self._actors_query_from_source(InsightActorsQuery(source=trends_query))

    def get_performed_event_multiple(self, prop: Property) -> ast.SelectQuery:
        count = parse_and_validate_positive_integer(prop.operator_value, "operator_value")

        if prop.explicit_datetime:
            date_from = prop.explicit_datetime
            date_to = prop.explicit_datetime_to
        else:
            date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
            date_interval = validate_interval(prop.time_interval)
            date_from = f"-{date_value}{date_interval[:1]}"
            date_to = None

        events_query = EventsQuery(after=date_from, before=date_to, select=["person_id", "count()"])
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
            date_to = prop.explicit_datetime_to
        else:
            date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
            date_interval = validate_interval(prop.time_interval)
            date_from = f"-{date_value}{date_interval[:1]}"
            date_to = None

        date_value = parse_and_validate_positive_integer(prop.seq_time_value, "seq_time_value")
        date_interval = validate_interval(prop.seq_time_interval)
        funnelWindowInterval = date_value * INTERVAL_TO_SECONDS[date_interval]

        funnel_query = FunnelsQuery(
            series=series,
            dateRange=DateRange(date_from=date_from, date_to=date_to),
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
        return _require_select_query(query_runner.to_query())

    def get_person_metadata_condition(self, prop: Property) -> ast.SelectQuery:
        # type = "person_metadata"
        # key = "created_at" (a top-level column on the persons table, not properties JSON)
        actors_query = ActorsQuery(
            properties=[
                PersonMetadataPropertyFilter(
                    key=prop.key, value=prop.value, operator=prop.operator or PropertyOperator.EXACT
                )
            ],
            select=["id"],
        )
        query_runner = ActorsQueryRunner(team=self.team, query=actors_query)
        return _require_select_query(query_runner.to_query())

    def get_static_cohort_condition(self, prop: Property) -> ast.SelectQuery:
        # Convert the cohort id to an int (not the no-op typing.cast) and bind it as a parameter.
        # prop.value is normally a cohort pk, but an internal cohort property smuggled through the
        # unvalidated legacy `groups` field could carry an arbitrary string; binding it (rather than
        # interpolating into parse_select) keeps it out of the query structure.
        if isinstance(prop.value, list):
            raise ValueError(f"cohort id must be an integer, got {prop.value}")
        cohort = Cohort.objects.get(
            pk=parse_and_validate_positive_integer(prop.value, "cohort id"), team__project_id=self.team.project_id
        )
        return cast(
            ast.SelectQuery,
            parse_select(
                # DISTINCT because `person_static_cohort` can hold repeated rows for the same member
                # (its sort key includes a per-row UUID), and this select is joined into other queries.
                "SELECT DISTINCT person_id as id FROM static_cohort_people WHERE cohort_id = {cohort_id} AND team_id = {team_id}",
                {"cohort_id": ast.Constant(value=cohort.pk), "team_id": ast.Constant(value=self.team.pk)},
            ),
        )

    def get_dynamic_cohort_condition(self, prop: Property) -> ast.SelectQuery:
        # See get_static_cohort_condition: convert + bind so a non-int value can't alter the query.
        if isinstance(prop.value, list):
            raise ValueError(f"cohort id must be an integer, got {prop.value}")
        cohort_id = parse_and_validate_positive_integer(prop.value, "cohort id")
        return cast(
            ast.SelectQuery,
            parse_select(
                "SELECT person_id as id FROM cohort_people WHERE cohort_id = {cohort_id} AND team_id = {team_id}",
                {"cohort_id": ast.Constant(value=cohort_id), "team_id": ast.Constant(value=self.team.pk)},
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
        elif prop.type == "person_metadata":
            return self.get_person_metadata_condition(prop)
        elif prop.type == "static-cohort":  # static cohorts are handled by flattening during initialization
            return self.get_static_cohort_condition(prop)
        elif prop.type == "dynamic-cohort":
            return self.get_dynamic_cohort_condition(prop)
        else:
            raise ValueError(f"Invalid property type for Cohort queries: {prop.type}")

    def _should_combine_person_properties_and(self) -> bool:
        return feature_enabled_or_false(
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

    def _should_combine_person_properties_or(self) -> bool:
        return feature_enabled_or_false(
            "hogql-cohort-combine-person-properties-or",
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
        should_combine_person_properties_and = self._should_combine_person_properties_and()
        should_combine_person_properties_or = self._should_combine_person_properties_or()

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

        def combine_person_properties(
            properties: Union[list[Property], list[PropertyGroup]], combine_type: PropertyOperatorType
        ) -> ast.SelectQuery:
            """
            Combine multiple person property filters into a single ActorsQuery.

            For AND: Replaces N queries with N-1 INTERSECT operations with a single query.
            For OR: Replaces N queries with N-1 UNION DISTINCT operations with a single query.
            """
            person_filters = []
            for prop_or_group in properties:
                prop = unwrap_property(prop_or_group)
                if prop is None:
                    continue
                person_filters.append(convert_property(prop))

            # AND: pass list directly (default behavior)
            # OR: wrap in PropertyGroupFilterValue
            query_properties: Union[list[PersonPropertyFilter], PropertyGroupFilterValue] = person_filters
            if combine_type == PropertyOperatorType.OR:
                query_properties = PropertyGroupFilterValue(
                    type=PropertyOperatorType.OR,
                    values=person_filters,
                )

            actors_query = ActorsQuery(
                properties=query_properties,
                select=["id"],
            )
            query_runner = ActorsQueryRunner(team=self.team, query=actors_query)
            return _require_select_query(query_runner.to_query())

        def build_conditions(
            prop: Optional[Union[PropertyGroup, Property]],
        ) -> Condition:
            if not prop:
                raise ValidationError("Cohort has a null property", str(prop))

            if isinstance(prop, Property):
                return Condition(self._get_condition_for_property(prop), prop.negation or False)

            if can_combine_person_properties(prop.values):
                if should_combine_person_properties_and and prop.type == PropertyOperatorType.AND:
                    return Condition(combine_person_properties(prop.values, PropertyOperatorType.AND), False)
                if should_combine_person_properties_or and prop.type == PropertyOperatorType.OR:
                    return Condition(combine_person_properties(prop.values, PropertyOperatorType.OR), False)

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
