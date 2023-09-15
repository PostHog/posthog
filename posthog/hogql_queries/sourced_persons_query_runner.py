from typing import Optional, Any, Dict

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models import Team
from posthog.schema import SourcedPersonsQuery, SourcedPersonsQueryResponse, LifecycleQuery


class SourcedPersonsQueryRunner(QueryRunner):
    query: SourcedPersonsQuery

    def __init__(self, query: SourcedPersonsQuery | Dict[str, Any], team: Team, timings: Optional[HogQLTimings] = None):
        super().__init__(team, timings)
        if isinstance(query, SourcedPersonsQuery):
            self.query = query
        else:
            self.query = SourcedPersonsQuery.parse_obj(query)

    def run(self) -> SourcedPersonsQueryResponse:
        response = execute_hogql_query(
            query_type="SourcedPersonsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
        )
        return SourcedPersonsQueryResponse(results=response.results, timings=response.timings, hogql=response.hogql)

    def to_query(self) -> ast.SelectQuery:
        source = self.query.source
        if isinstance(source, LifecycleQuery):
            query = get_query_runner(source, self.team, self.timings).to_persons_query()
            return parse_select(
                "select * from persons where id in {query}", placeholders={"query": query}, timings=self.timings
            )

        raise ValueError(f"Can't get a runner for an unknown query kind: {source.kind}")

    def to_persons_query(self) -> ast.SelectQuery:
        return self.to_query()
