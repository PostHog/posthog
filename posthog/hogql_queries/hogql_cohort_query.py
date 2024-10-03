from typing import Literal

from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.legacy_compatibility.clean_properties import clean_global_properties
from posthog.models import Filter, Cohort
from posthog.schema import ActorsQuery
from posthog.queries.cohort_query import CohortQuery


class HogQLCohortQuery:
    def __init__(self, cohort_query: CohortQuery, cohort: Cohort = None):
        # self.cohort = cohort

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

        # Shared props, these help with testing
        self.properties = clean_global_properties(self.cohort_query._filter._data["properties"])
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

    def query_str(self, dialect: Literal["hogql", "clickhouse"]):
        return print_ast(self.get_query(), self.hogql_context, dialect, pretty=True)
