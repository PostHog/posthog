import abc
from posthog.hogql import ast
from typing import List, Optional
from posthog.schema import Breakdown
from posthog.hogql_queries.insights.trends.aggregation_operations import (
    AggregationOperations,
)


class TrendsQueryBuilderAbstract(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def build_query(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        pass

    @abc.abstractmethod
    def _get_date_subqueries(self, breakdown: Breakdown, ignore_breakdowns: bool = False) -> List[ast.SelectQuery]:
        pass

    @abc.abstractmethod
    def _get_events_subquery(
        self,
        no_modifications: Optional[bool],
        is_actors_query: bool,
        breakdown: Breakdown,
        breakdown_values_override: Optional[str | int] = None,
        actors_query_time_frame: Optional[str | int] = None,
    ) -> ast.SelectQuery:
        pass

    @abc.abstractmethod
    def _outer_select_query(self, breakdown: Breakdown, inner_query: ast.SelectQuery) -> ast.SelectQuery:
        pass

    @abc.abstractmethod
    def _inner_select_query(
        self, breakdown: Breakdown, inner_query: ast.SelectQuery | ast.SelectUnionQuery
    ) -> ast.SelectQuery:
        pass

    @abc.abstractmethod
    def _events_filter(
        self,
        is_actors_query: bool,
        breakdown: Breakdown | None,
        ignore_breakdowns: bool = False,
        breakdown_values_override: Optional[str | int] = None,
        actors_query_time_frame: Optional[str | int] = None,
    ) -> ast.Expr:
        pass

    @abc.abstractmethod
    def _breakdown(self, is_actors_query: bool, breakdown_values_override: Optional[str | int] = None):
        pass

    @abc.abstractmethod
    def _aggregation_operation(self) -> AggregationOperations:
        pass
