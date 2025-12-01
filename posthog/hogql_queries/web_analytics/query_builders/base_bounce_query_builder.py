from abc import abstractmethod
from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.property import get_property_type, property_to_expr

from posthog.hogql_queries.web_analytics.query_builders.base import BaseStatsTableQueryBuilder

if TYPE_CHECKING:
    from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner


class BaseBounceQueryBuilder(BaseStatsTableQueryBuilder):
    def __init__(self, runner: "WebStatsTableQueryRunner"):
        super().__init__(runner)

    @abstractmethod
    def build(self) -> ast.SelectQuery:
        pass

    def _session_properties(self) -> ast.Expr:
        properties = [
            p
            for p in self.runner.query.properties + self.runner._test_account_filters
            if get_property_type(p) == "session"
        ]
        return property_to_expr(properties, team=self.runner.team, scope="event")

    def _event_properties(self) -> ast.Expr:
        properties = [
            p
            for p in self.runner.query.properties + self.runner._test_account_filters
            if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.runner.team, scope="event")

    def _bounce_entry_pathname_breakdown(self) -> ast.Expr:
        return self.runner._apply_path_cleaning(ast.Field(chain=["session", "$entry_pathname"]))

    def _current_period_expression(self) -> ast.Expr:
        return self.runner._current_period_expression()

    def _previous_period_expression(self) -> ast.Expr:
        return self.runner._previous_period_expression()

    def _apply_order_and_fill(self, query: ast.SelectQuery) -> ast.SelectQuery:
        """Apply ordering and fill fraction to the query. Shared logic for bounce builders."""
        columns = [select.alias for select in query.select if isinstance(select, ast.Alias)]
        query.order_by = self._order_by(columns)

        fill_fraction = self._fill_fraction(query.order_by)
        if fill_fraction:
            query.select.append(fill_fraction)

        return query
