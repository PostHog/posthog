from typing import cast

from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.event_sessions import CleanTableNameFromChain, WhereClauseExtractor
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import clone_expr


class TestWhereClauseExtractor(BaseTest):
    def setUp(self):
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(database=self.database, team_id=self.team.pk)

    def _select(self, query: str) -> ast.SelectQuery:
        select_query = cast(ast.SelectQuery, clone_expr(parse_select(query), clear_locations=True))
        return cast(ast.SelectQuery, resolve_types(select_query, self.context, dialect="clickhouse"))

    def _compare_operators(self, query: ast.SelectQuery, table_name: str) -> list[ast.Expr]:
        assert query.where is not None and query.type is not None
        return WhereClauseExtractor(query.where, table_name, query.type, self.context).compare_operators

    def test_with_simple_equality_clause(self):
        query = self._select(
            """
                SELECT event
                FROM events
                WHERE team_id = 1
            """
        )

        compare_operators = self._compare_operators(query, "events")

        assert len(compare_operators) == 1
        assert compare_operators[0] == ast.CompareOperation(
            left=ast.Alias(alias="team_id", hidden=True, expr=ast.Field(chain=["team_id"])),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value=1),
        )

    def test_with_timestamps(self):
        query = self._select(
            """
                SELECT event
                FROM events
                WHERE timestamp > '2023-01-01'
            """
        )

        compare_operators = self._compare_operators(query, "events")

        assert len(compare_operators) == 1
        assert compare_operators[0] == ast.CompareOperation(
            left=ast.Alias(alias="timestamp", hidden=True, expr=ast.Field(chain=["timestamp"])),
            op=ast.CompareOperationOp.Gt,
            right=ast.Constant(value="2023-01-01"),
        )

    def test_with_alias_table(self):
        query = self._select(
            """
                SELECT e.event
                FROM events e
                WHERE e.team_id = 1
            """
        )

        compare_operators = self._compare_operators(query, "e")

        assert len(compare_operators) == 1
        assert compare_operators[0] == ast.CompareOperation(
            left=ast.Alias(alias="team_id", hidden=True, expr=ast.Field(chain=["team_id"])),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value=1),
        )

    def test_with_multiple_clauses(self):
        query = self._select(
            """
                SELECT event
                FROM events
                WHERE team_id = 1 AND timestamp > '2023-01-01'
            """
        )

        compare_operators = self._compare_operators(query, "events")

        assert len(compare_operators) == 2
        assert compare_operators[0] == ast.CompareOperation(
            left=ast.Alias(alias="team_id", hidden=True, expr=ast.Field(chain=["team_id"])),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value=1),
        )
        assert compare_operators[1] == ast.CompareOperation(
            left=ast.Alias(alias="timestamp", hidden=True, expr=ast.Field(chain=["timestamp"])),
            op=ast.CompareOperationOp.Gt,
            right=ast.Constant(value="2023-01-01"),
        )

    def test_with_join(self):
        query = self._select(
            """
                SELECT e.event, p.id
                FROM events e
                LEFT JOIN persons p
                ON e.person_id = p.id
                WHERE e.team_id = 1 and p.is_identified = 0
            """
        )

        compare_operators = self._compare_operators(query, "e")

        assert len(compare_operators) == 1
        assert compare_operators[0] == ast.CompareOperation(
            left=ast.Alias(alias="team_id", hidden=True, expr=ast.Field(chain=["team_id"])),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value=1),
        )

    def test_with_ignoring_ors(self):
        query = self._select(
            """
                SELECT event
                FROM events
                WHERE team_id = 1 OR team_id = 2
            """
        )

        compare_operators = self._compare_operators(query, "events")

        assert len(compare_operators) == 0


class TestCleanTableNameFromChain(BaseTest):
    def setUp(self):
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(database=self.database, team_id=self.team.pk)

    def _select(self, query: str) -> ast.SelectQuery:
        select_query = cast(ast.SelectQuery, clone_expr(parse_select(query), clear_locations=True))
        return cast(ast.SelectQuery, resolve_types(select_query, self.context, dialect="clickhouse"))

    def _clean(self, table_name: str, query: ast.SelectQuery, expr: ast.Expr) -> ast.Expr:
        assert query.type is not None
        return CleanTableNameFromChain(table_name, query.type).visit(expr)

    def test_table_with_no_alias(self):
        query = self._select(
            """
                SELECT event
                FROM events
            """
        )

        expr = parse_expr('event = "$pageview"')
        cleaned_expr = cast(ast.CompareOperation, self._clean("events", query, expr))
        expr_left = cast(ast.Field, cleaned_expr.left)

        assert expr_left.chain == ["event"]

    def test_table_with_alias(self):
        query = self._select(
            """
                SELECT e.event
                FROM events e
            """
        )

        expr = parse_expr('e.event = "$pageview"')
        cleaned_expr = cast(ast.CompareOperation, self._clean("e", query, expr))
        expr_left = cast(ast.Field, cleaned_expr.left)

        assert expr_left.chain == ["event"]

    def test_field_with_properties(self):
        query = self._select(
            """
                SELECT event
                FROM events
            """
        )

        expr = parse_expr('properties.$browser = "Chrome"')
        cleaned_expr = cast(ast.CompareOperation, self._clean("events", query, expr))
        expr_left = cast(ast.Field, cleaned_expr.left)

        assert expr_left.chain == ["properties", "$browser"]

    def test_table_alias_and_field_with_properties(self):
        query = self._select(
            """
                SELECT e.event
                FROM events e
            """
        )

        expr = parse_expr('e.properties.$browser = "Chrome"')
        cleaned_expr = cast(ast.CompareOperation, self._clean("e", query, expr))
        expr_left = cast(ast.Field, cleaned_expr.left)

        assert expr_left.chain == ["properties", "$browser"]

    def test_with_incorrect_alias(self):
        query = self._select(
            """
                SELECT e.event
                FROM events e
            """
        )

        expr = parse_expr('e.event = "$pageview"')
        cleaned_expr = cast(ast.CompareOperation, self._clean("some_other_alias", query, expr))
        expr_left = cast(ast.Field, cleaned_expr.left)

        assert expr_left.chain == ["e", "event"]
