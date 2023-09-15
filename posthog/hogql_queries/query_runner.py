from typing import Optional, Any, Dict

from pydantic import BaseModel

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from posthog.hogql.timings import HogQLTimings
from posthog.models import Team


def get_query_runner(
    query: Dict[str, Any] | BaseModel, team: Team, timings: Optional[HogQLTimings] = None
) -> "QueryRunner":
    kind = None
    if isinstance(query, dict):
        kind = query.get("kind", None)
    elif hasattr(query, "kind"):
        kind = query.kind

    if kind == "LifecycleQuery":
        from .lifecycle_query_runner import LifecycleQueryRunner

        return LifecycleQueryRunner(query=query, team=team, timings=timings)
    if kind == "SourcedPersonsQuery":
        from .sourced_persons_query_runner import SourcedPersonsQueryRunner

        return SourcedPersonsQueryRunner(query=query, team=team, timings=timings)
    raise ValueError(f"Can't get a runner for an unknown query kind: {kind}")


class QueryRunner:
    query: BaseModel
    team: Team
    timings: HogQLTimings

    def __init__(self, team: Team, timings: Optional[HogQLTimings] = None):
        self.team = team
        self.timings = timings or HogQLTimings()

    def run(self) -> BaseModel:
        raise NotImplementedError()

    def to_query(self) -> ast.SelectQuery:
        raise NotImplementedError()

    def to_persons_query(self) -> str:
        # TODO: add support for selecting and filtering by breakdowns
        raise NotImplementedError()

    def to_hogql(self) -> str:
        with self.timings.measure("to_hogql"):
            return print_ast(
                self.to_query(),
                HogQLContext(team_id=self.team.pk, enable_select_queries=True, timings=self.timings),
                "hogql",
            )
