from typing import Literal, Optional, Union, Any

from rest_framework.exceptions import ValidationError

from posthog.constants import PropertyOperatorType
from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery, SelectUnionNode
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.legacy_compatibility.clean_properties import clean_global_properties
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models import Filter, Cohort, Team, Property
from posthog.models.cohort.util import get_count_operator
from posthog.models.property import PropertyGroup
from posthog.queries.foss_cohort_query import validate_interval, parse_and_validate_positive_integer
from posthog.schema import (
    ActorsQuery,
    InsightActorsQuery,
    TrendsQuery,
    InsightDateRange,
    TrendsFilter,
    EventsNode,
    ActionsNode,
    BaseMathType,
    FunnelsQuery,
    FunnelsActorsQuery,
    FunnelsFilter,
    FunnelConversionWindowTimeUnit,
)
from posthog.queries.cohort_query import CohortQuery
from posthog.temporal.tests.utils.datetimes import date_range


class TestWrapperCohortQuery(CohortQuery):
    def __init__(self, filter: Filter, team: Team):
        cohort_query = CohortQuery(filter=filter, team=team)
        hogql_cohort_query = HogQLCohortQuery(cohort_query=cohort_query)
        hogql_query = hogql_cohort_query.query_str("hogql")
        self.result = execute_hogql_query(hogql_query, team)
        super().__init__(filter=filter, team=team)


class HogQLCohortQuery:
    def __init__(self, cohort_query: CohortQuery, cohort: Cohort = None):
        self.hogql_context = HogQLContext(team_id=cohort_query._team_id, enable_select_queries=True)

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

    def get_query(self) -> SelectQuery:
        if not self.cohort_query._outer_property_groups:
            # everything is pushed down, no behavioral stuff to do
            # thus, use personQuery directly

            # This works
            # ActorsQuery(properties=c.properties.to_dict())

            # This just queries based on person properties and stuff
            # Need to figure out how to turn these cohort properties into a set of person properties
            # actors_query = ActorsQuery(properties=self.cohort.properties.to_dict())
            # query_runner = ActorsQueryRunner(team=self.cohort.team, query=actors_query)
            actors_query = ActorsQuery(properties=self.properties, select=["id"])
            query_runner = ActorsQueryRunner(team=self.team, query=actors_query)
            return query_runner.to_query()

        # self._get_conditions()
        # self.get_performed_event_condition()

        # Work on getting testing passing
        # current test: test_performed_event
        # special code this for test_performed_event
        # self.properties["values"][0]["values"][0]

        # self.get_performed_event_condition()
        # property = self._outer_property_groups.values[0].values[0]
        # self.get_performed_event_condition(property)
        select_query = self._get_conditions()
        return select_query

    def query_str(self, dialect: Literal["hogql", "clickhouse"]):
        return print_ast(self.get_query(), self.hogql_context, dialect, pretty=True)

    def get_performed_event_condition(self, prop: Property, first_time: bool = False) -> ast.SelectQuery:
        math = None
        if first_time:
            math = BaseMathType.FIRST_TIME_FOR_USER
        # either an action or an event
        if prop.event_type == "events":
            series = [EventsNode(event=prop.key, math=math)]
        elif prop.event_type == "actions":
            series = [ActionsNode(id=int(prop.key), math=math)]
        else:
            raise ValueError(f"Event type must be 'events' or 'actions'")

        if prop.event_filters:
            filter = Filter(data={"properties": prop.event_filters}).property_groups
            series[0].properties = filter

        if prop.explicit_datetime:
            # Explicit datetime filter, can be a relative or absolute date, follows same convention
            # as all analytics datetime filters
            # date_param = f"{prepend}_explicit_date_{idx}"
            # target_datetime = relative_date_parse(prop.explicit_datetime, self._team.timezone_info)

            # Do this to create global filters for the entire query
            # relative_date = self._get_relative_interval_from_explicit_date(target_datetime, self._team.timezone_info)
            # self._check_earliest_date(relative_date)

            # return f"timestamp > %({date_param})s", {f"{date_param}": target_datetime}
            date_from = prop.explicit_datetime
        else:
            date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
            date_interval = validate_interval(prop.time_interval)
            date_from = f"-{date_value}{date_interval[:1]}"

        trends_query = TrendsQuery(
            dateRange=InsightDateRange(date_from=date_from),
            trendsFilter=TrendsFilter(display="ActionsBarValue"),
            series=series,
        )

        actors_query = ActorsQuery(
            source=InsightActorsQuery(source=trends_query),
            select=["id"],
        )

        return ActorsQueryRunner(team=self.team, query=actors_query).to_query()

    def get_performed_event_multiple(self, prop: Property) -> ast.SelectQuery:
        count = parse_and_validate_positive_integer(prop.operator_value, "operator_value")
        # either an action or an event
        if prop.event_type == "events":
            series = [EventsNode(event=prop.key)] * (count + 1)
        elif prop.event_type == "actions":
            series = [ActionsNode(id=int(prop.key))] * (count + 1)
        else:
            raise ValueError(f"Event type must be 'events' or 'actions'")

        # negation here means we're excluding users, not including them
        # for example (users who have performed action "click here" 1 or less times)
        # we subtract the set of users we get back from the set (we require a positive cohort thing somewhere)
        # negation = False

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
            series[0].properties = filter

        if prop.explicit_datetime:
            date_from = prop.explicit_datetime
        else:
            date_value = parse_and_validate_positive_integer(prop.time_value, "time_value")
            date_interval = validate_interval(prop.time_interval)
            date_from = f"-{date_value}{date_interval[:1]}"

        funnel_query = FunnelsQuery(
            series=series,
            dateRange=InsightDateRange(date_from=date_from),
            funnelsFilter=FunnelsFilter(
                funnelWindowInterval=12 * 50, funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.MONTH
            ),
        )
        actors_query = actors_query = ActorsQuery(
            source=FunnelsActorsQuery(source=funnel_query, funnelStep=funnelStep, funnelCustomSteps=funnelCustomSteps),
            select=["id"],
        )

        return ActorsQueryRunner(team=self.team, query=actors_query).to_query()

    def _get_condition_for_property(self, prop: Property) -> ast.SelectQuery | ast.SelectUnionQuery:
        res: str = ""
        params: dict[str, Any] = {}

        prepend = ""
        idx = 0

        if prop.type == "behavioral":
            if prop.value == "performed_event":
                return self.get_performed_event_condition(prop)
            elif prop.value == "performed_event_first_time":
                return self.get_performed_event_condition(prop, True)
            elif prop.value == "performed_event_multiple":
                return self.get_performed_event_multiple(prop)
            elif prop.value == "stopped_performing_event":
                res, params = self.get_stopped_performing_event(prop, prepend, idx)
            elif prop.value == "restarted_performing_event":
                res, params = self.get_restarted_performing_event(prop, prepend, idx)
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
        else:
            raise ValueError(f"Invalid property type for Cohort queries: {prop.type}")

        return res

    def _get_conditions(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        def build_conditions(
            prop: Optional[Union[PropertyGroup, Property]]
        ) -> None | ast.SelectQuery | ast.SelectUnionQuery:
            if not prop:
                # What do we do here?
                return None

            if isinstance(prop, PropertyGroup):
                queries = []
                for idx, property in enumerate(prop.values):
                    query = build_conditions(property)  # type: ignore
                    if query is not None:
                        queries.append(query)
                        # params.update(q_params)

                # TODO: make this do union or intersection based on prop.type
                if prop.type == PropertyOperatorType.OR:
                    return ast.SelectUnionQuery(
                        select_queries=[
                            SelectUnionNode(select_query=query, union_type="UNION ALL" if query != queries[0] else None)
                            for query in queries
                        ]
                    )
                return ast.SelectUnionQuery(
                    select_queries=[
                        SelectUnionNode(select_query=query, union_type="INTERSECT" if query != queries[0] else None)
                        for query in queries
                    ]
                )
            else:
                return self._get_condition_for_property(prop)

        conditions = build_conditions(self._outer_property_groups)
        return conditions
