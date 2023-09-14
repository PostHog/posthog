from typing import Optional

from pydantic import BaseModel

from posthog.hogql import ast
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
        pass
