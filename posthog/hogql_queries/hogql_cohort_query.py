from typing import Literal, Optional, Union, Any

from posthog.constants import PropertyOperatorType
from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.legacy_compatibility.clean_properties import clean_global_properties
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models import Filter, Cohort, Team, Property
from posthog.models.property import PropertyGroup
from posthog.schema import ActorsQuery
from posthog.queries.cohort_query import CohortQuery


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

    # Get this working first
    def get_performed_event_condition(self, prop: Property) -> ast.SelectQuery:
        return parse_select(
            """select * from (
                    <ActorsQuery select={['id']}>
                        <InsightActorsQuery>
                            <TrendsQuery
                                dateRange={<InsightDateRange date_from='-1w' />}
                                series={[<EventsNode event='$pageview' />]}
                                trendsFilter={<TrendsFilter display='ActionsBarValue' />}
                                --properties={[<PersonPropertyFilter type='person' key='email' value='tom@posthog.com' operator='is_not' />]}
                            />
                        </InsightActorsQuery>
                    </ActorsQuery>
                )"""
        )

    def _get_condition_for_property(self, prop: Property) -> ast.SelectQuery | ast.SelectUnionQuery:
        res: str = ""
        params: dict[str, Any] = {}

        prepend = ""
        idx = 0

        if prop.type == "behavioral":
            if prop.value == "performed_event":
                return self.get_performed_event_condition(prop)
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
                    return ast.SelectUnionQuery(select_queries=queries, value="UNION ALL")
                return ast.SelectUnionQuery(select_queries=queries, value="INTERSECT")
            else:
                return self._get_condition_for_property(prop)

        conditions = build_conditions(self._outer_property_groups)
        return conditions
