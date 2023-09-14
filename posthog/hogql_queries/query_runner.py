from typing import Optional

from pydantic import BaseModel

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from posthog.hogql.timings import HogQLTimings
from posthog.models import Team


class QueryRunner:
    query: BaseModel
    team: Team
    timings: HogQLTimings

    def __init__(self, team: Team, timings: Optional[HogQLTimings] = None):
        self.team = team
        self.timings = timings or HogQLTimings()

    def run(self) -> BaseModel:
        pass

    def to_ast(self) -> ast.SelectQuery:
        pass

    def to_hogql(self) -> str:
        with self.timings.measure("to_hogql"):
            return print_ast(
                self.to_ast(),
                HogQLContext(team_id=self.team.pk, enable_select_queries=True, timings=self.timings),
                "hogql",
            )
