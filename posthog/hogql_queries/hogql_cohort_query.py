from typing import Any

from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.models import Filter
from posthog.schema import ActorsQuery
from posthog.queries.cohort_query import CohortQuery


class HogQLCohortQuery:

    def __init__(self, cohort):
        self.cohort = cohort

        self.hogql_context = HogQLContext(team_id=cohort.team_id)

        self.cohort_query = CohortQuery(
            Filter(
                data={"properties": cohort.properties},
                team=cohort.team,
                hogql_context=self.hogql_context,
            ),
            cohort.team,
            cohort_pk=cohort.pk,
        )

    def get_query(self) -> tuple[str, dict[str, Any]]:
        if not self.cohort_query._outer_property_groups:
            # everything is pushed down, no behavioral stuff to do
            # thus, use personQuery directly

            # This works
            # ActorsQuery(properties=c.properties.to_dict())

            # This just queries based on person properties and stuff
            # Need to figure out how to turn these cohort properties into a set of person properties
            actors_query = ActorsQuery(properties=self.cohort.properties.to_dict())
            query_runner = ActorsQueryRunner(team=self.cohort.team, query=actors_query)
            return query_runner.to_query()

    def print(self):
        return print_ast(self.get_query(), self.hogql_context, 'hogql')