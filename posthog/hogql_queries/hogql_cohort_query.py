from typing import Literal, Optional, Union, cast

from rest_framework.exceptions import ValidationError

from posthog.constants import PropertyOperatorType
from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery, SelectSetNode, SelectSetQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.models import Filter, Cohort, Team, Property
from posthog.models.property import PropertyGroup
from posthog.queries.foss_cohort_query import (
    validate_interval,
    parse_and_validate_positive_integer,
    INTERVAL_TO_SECONDS,
)
from posthog.schema import (
    ActorsQuery,
    InsightActorsQuery,
    TrendsQuery,
    DateRange,
    TrendsFilter,
    EventsNode,
    ActionsNode,
    BaseMathType,
    FunnelsQuery,
    FunnelsActorsQuery,
    FunnelsFilter,
    FunnelConversionWindowTimeUnit,
    StickinessQuery,
    StickinessFilter,
    StickinessCriteria,
    StickinessActorsQuery,
    PersonPropertyFilter,
    PropertyOperator,
    PropertyGroupFilterValue,
    PersonsOnEventsMode,
)
from posthog.queries.cohort_query import CohortQuery


class TestWrapperCohortQuery(CohortQuery):
    def __init__(self, filter: Filter, team: Team):
        cohort_query = CohortQuery(filter=filter, team=team)
        hogql_cohort_query = HogQLCohortQuery(cohort_query=cohort_query)
        # hogql_query = hogql_cohort_query.query_str("hogql")
        self.result = execute_hogql_query(hogql_cohort_query.get_query(), team)
        super().__init__(filter=filter, team=team)


def convert_property(prop: Property) -> PersonPropertyFilter:
    return PersonPropertyFilter(key=prop.key, value=prop.value, operator=prop.operator or PropertyOperator.EXACT)


def convert(prop: PropertyGroup) -> PropertyGroupFilterValue:
    r = PropertyGroupFilterValue(
        type=prop.type,
        values=[convert(x) if isinstance(x, PropertyGroup) else convert_property(x) for x in prop.values],
    )
    return r


class HogQLCohortQuery:
    def __init__(self, cohort_query: CohortQuery = None, cohort: Cohort = None):
        team_id = (cohort and cohort.team.pk) or cohort_query._team_id
        self.hogql_context = HogQLContext(team_id=team_id, enable_select_queries=True)

        if cohort is not None:
            self.cohort_query = CohortQuery(
                Filter(
                    data={"properties": cohort.properties},
                    team=cohort.team,
                    hogql_context=self.hogql_context,
                ),
                cohort.team,
                cohort_pk=cohort.pk,
            )
        else:
            self.cohort_query = cohort_query

        # self.properties = clean_global_properties(self.cohort_query._filter._data["properties"])
        self._inner_property_groups = self.cohort_query._inner_property_groups
        self._outer_property_groups = self.cohort_query._outer_property_groups
        self.team = self.cohort_query._team

    def _actors_query(self):
        pgfv = convert(self._inner_property_groups)
        actors_query = ActorsQuery(properties=pgfv, select=["id"])
        query_runner = ActorsQueryRunner(team=self.team, query=actors_query)
        return query_runner.to_query()

    def get_query(self) -> SelectQuery:
        if not self.cohort_query._outer_property_groups:
            # everything is pushed down, no behavioral stuff to do
            # thus, use personQuery directly
            return self._actors_query()

        select_query = self._get_conditions()

        if self.cohort_query._should_join_persons and self.cohort_query._inner_property_groups:
            actors_query = self._actors_query()
            """
            hogql_actors = print_ast(
                actors_query,
                HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True),
                dialect="hogql",
                pretty=True,
            )
            """
            if self.cohort_query.should_pushdown_persons:
                if (
                    self.cohort_query._person_on_events_mode
                    == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
                ):
                    # when using person-on-events, instead of inner join, we filter inside
                    # the event query itself
                    pass
                else:
                    select_query = SelectSetQuery(
                        initial_select_query=select_query,
                        subsequent_select_queries=[SelectSetNode(select_query=actors_query, set_operator="INTERSECT")],
                    )
            else:
                pass
                # not sure what this is for
                """
                q = f"{q} {full_outer_join_query(subq_query, subq_alias, f'{subq_alias}.person_id', f'{prev_alias}.person_id')}"
                    fields = if_condition(
                        f"{prev_alias}.person_id = '00000000-0000-0000-0000-000000000000'",
                        f"{subq_alias}.person_id",
                        f"{fields}",
                    )"""

        """
        hogql = print_ast(
            select_query,
            HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True),
            dialect="hogql",
            pretty=True,
        )
        """

        return select_query

    def query_str(self, dialect: Literal["hogql", "clickhouse"]):
        return print_ast(self.get_query(), self.hogql_context, dialect, pretty=True)

    def _get_series(self, prop: Property, math=None):
        if prop.event_type == "events":
            return [EventsNode(event=prop.key, math=math)]
        elif prop.event_type == "actions":
            return [ActionsNode(id=int(prop.key), math=math)]
        else:
            raise ValueError(f"Event type must be 'events' or 'actions'")

    def _actors_query_from_source(self, source: Union[InsightActorsQuery, FunnelsActorsQuery]) -> ast.SelectQuery:
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
        # either an action or an event
        if prop.event_type == "events":
            series = [EventsNode(event=prop.key)] * (count + 1)
        elif prop.event_type == "actions":
            series = [ActionsNode(id=int(prop.key))] * (count + 1)
        else:
            raise ValueError(f"Event type must be 'events' or 'actions'")

        funnelStep: int = None

        funnelCustomSteps: list[int] = None

        if prop.operator == "gte":
            funnelStep = count
        elif prop.operator == "lte":
            funnelCustomSteps = list(range(1, count + 1))
        elif prop.operator == "gt":
            funnelStep = count + 1
        elif prop.operator == "lt":
            funnelCustomSteps = list(range(1, count))
        elif prop.operator == "eq" or prop.operator == "exact" or prop.operator is None:
            # People who dropped out at count + 1
            funnelStep = -(count + 1)
        else:
            raise ValidationError("count_operator must be gte, lte, eq, or None")

        if prop.event_filters:
            filter = Filter(data={"properties": prop.event_filters}).property_groups
            # TODO: this is testing - we need to figure out how to handle ORs here
            if isinstance(filter, PropertyGroup):
                if filter.type == PropertyOperatorType.OR:
                    raise Exception("Don't support OR at the event level")
                series[0].properties = filter.values
            else:
                series[0].properties = filter

        if prop.explicit_datetime:
            date_from = prop.explicit_datetime
        else:
            date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
            date_interval = validate_interval(prop.time_interval)
            date_from = f"-{date_value}{date_interval[:1]}"

        funnel_query = FunnelsQuery(
            series=series,
            dateRange=DateRange(date_from=date_from),
            funnelsFilter=FunnelsFilter(
                funnelWindowInterval=12 * 50, funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.MONTH
            ),
        )
        return self._actors_query_from_source(
            FunnelsActorsQuery(source=funnel_query, funnelStep=funnelStep, funnelCustomSteps=funnelCustomSteps)
        )

    def get_performed_event_sequence(self, prop: Property) -> ast.SelectQuery:
        # either an action or an event
        series = []
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

        """
        if prop.event_filters:
            filter = Filter(data={"properties": prop.event_filters}).property_groups
            series[0].properties = filter
        """

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

    def get_performed_event_regularly(self, prop: Property) -> ast.SelectSetQuery:
        # min_periods
        # operator (gte)
        # operator_value (int)
        # time_interval
        # time_value
        # total periods

        series = self._get_series(prop)

        date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
        date_interval = validate_interval(prop.time_interval)
        date_from = f"-{date_value}{date_interval[:1]}"

        stickiness_query = StickinessQuery(
            series=series,
            dateRange=DateRange(date_from=date_from),
            stickinessFilter=StickinessFilter(
                stickinessCriteria=StickinessCriteria(operator=prop.operator, value=prop.operator_value)
            ),
        )
        return self._actors_query_from_source(
            StickinessActorsQuery(source=stickiness_query, day=prop.min_periods - 1, operator=prop.operator)
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
        return parse_select(
            f"SELECT person_id FROM static_cohort_people WHERE cohort_id = {cohort.pk} AND team_id = {self.team.pk}",
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
        elif prop.type == "person":
            return self.get_person_condition(prop)
        elif (
            prop.type == "static-cohort"
        ):  # "cohort" and "precalculated-cohort" are handled by flattening during initialization
            return self.get_static_cohort_condition(prop)
        else:
            raise ValueError(f"Invalid property type for Cohort queries: {prop.type}")

    def _get_conditions(self) -> ast.SelectQuery | ast.SelectSetQuery:
        def build_conditions(
            prop: Optional[Union[PropertyGroup, Property]],
        ) -> (None | ast.SelectQuery | ast.SelectSetQuery, bool):
            if not prop:
                # What do we do here?
                return (None, False)

            if isinstance(prop, PropertyGroup):
                queries = []
                for property in prop.values:
                    query, negation = build_conditions(property)  # type: ignore
                    if query is not None:
                        queries.append((query, negation))

                all_negated = all(x[1] for x in queries)
                all_not_negated = all(not x[1] for x in queries)
                """
                hogql = [
                    print_ast(
                        query,
                        HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True),
                        dialect="hogql",
                        pretty=True,
                    )
                    for query, negation in queries
                ]
                """
                negated = False
                if prop.type == PropertyOperatorType.OR:
                    if all_negated or all_not_negated:
                        return (
                            ast.SelectSetQuery(
                                initial_select_query=queries[0][0],
                                subsequent_select_queries=[
                                    SelectSetNode(select_query=query, set_operator="UNION DISTINCT")
                                    for (query, negation) in queries[1:]
                                ],
                            ),
                            all_negated,
                        )
                    else:
                        negated = True
                        queries = [(query, not negation) for query, negation in queries]
                # Negation criteria can only be used when matching all criteria (AND), and must be accompanied by at least one positive matching criteria.
                queries.sort(key=lambda query: query[1])  # False before True
                return (
                    ast.SelectSetQuery(
                        initial_select_query=queries[0][0],
                        subsequent_select_queries=[
                            SelectSetNode(
                                select_query=query,
                                set_operator="UNION DISTINCT"
                                if all_negated
                                else ("EXCEPT" if negation else "INTERSECT"),
                            )
                            for (query, negation) in queries[1:]
                        ],
                    ),
                    all_negated or negated,
                )
            else:
                return (self._get_condition_for_property(prop), prop.negation)

        conditions, _ = build_conditions(self._outer_property_groups)
        return conditions
