from abc import ABC, abstractmethod
from typing import Any, Optional, Type, Dict

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from posthog.hogql.timings import HogQLTimings
from posthog.models import Team
from posthog.types import InsightQueryNode
from posthog.utils import generate_cache_key


class QueryRunner(ABC):
    query: InsightQueryNode
    query_type: Type[InsightQueryNode]
    team: Team
    timings: HogQLTimings

    def __init__(self, query: InsightQueryNode | Dict[str, Any], team: Team, timings: Optional[HogQLTimings] = None):
        self.team = team
        self.timings = timings or HogQLTimings()
        if isinstance(query, self.query_type):
            self.query = query
        else:
            self.query = self.query_type.model_validate(query)

    @abstractmethod
    def run(self) -> InsightQueryNode:
        raise NotImplementedError()

    @abstractmethod
    def to_query(self) -> ast.SelectQuery:
        raise NotImplementedError()

    @abstractmethod
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

    def toJSON(self) -> str:
        return self.query.model_dump_json(exclude_defaults=True, exclude_none=True)

    def cache_key(self, cache_invalidation_key: Optional[str] = None):
        payload = f"query_{self.query.kind}_{self.toJSON()}_{self.team.pk}"
        if cache_invalidation_key:
            payload += f"_{cache_invalidation_key}"

        return generate_cache_key(payload)
