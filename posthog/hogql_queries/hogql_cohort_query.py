from typing import Any

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.schema import ActorsQuery
from posthog.queries.cohort_query import CohortQuery


class HogQLCohortQuery(CohortQuery):

    def get_query(self) -> tuple[str, dict[str, Any]]:
        if not self._outer_property_groups:
            # everything is pushed down, no behavioral stuff to do
            # thus, use personQuery directly

            # This just queries based on person properties and stuff
            # Need to figure out how to turn these cohort properties into a set of person properties
            actors_query = ActorsQuery(properties=[self._filter._data["properties"]])
            query_runner = ActorsQueryRunner(team=self._team, query=actors_query)
            return query_runner.to_query()