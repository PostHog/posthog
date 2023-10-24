from typing import cast
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.database.schema.event_sessions import EventsSessionWhereClauseTraverser
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import clone_expr
from posthog.test.base import BaseTest


class TestEventsSessionWhereClauseTraverser(BaseTest):
    def setUp(self):
        self.database = create_hogql_database(self.team.pk)
        self.context = HogQLContext(database=self.database, team_id=self.team.pk)

    def _select(self, query: str) -> ast.SelectQuery:
        select_query = cast(ast.SelectQuery, clone_expr(parse_select(query), clear_locations=True))
        return resolve_types(select_query, self.context)

    def test_with_simple_equality_clause(self):
        query = self._select(
            """
                SELECT event
                FROM events
                WHERE event = '$pageview'
            """
        )

        compare_operators = EventsSessionWhereClauseTraverser(query, self.context).compare_operators

        assert len(compare_operators) == 1
        assert compare_operators[0] == ast.CompareOperation(
            left=ast.Field(chain=["event"]), op=ast.CompareOperationOp.Eq, right=ast.Constant(value="$pageview")
        )

    def test_with_timestamps(self):
        query = self._select(
            """
                SELECT event
                FROM events
                WHERE timestamp > '2023-01-01'
            """
        )

        compare_operators = EventsSessionWhereClauseTraverser(query, self.context).compare_operators

        assert len(compare_operators) == 1
        assert compare_operators[0] == ast.CompareOperation(
            left=ast.Field(chain=["timestamp"]), op=ast.CompareOperationOp.Gt, right=ast.Constant(value="2023-01-01")
        )

    def test_with_alias_table(self):
        query = self._select(
            """
                SELECT e.event
                FROM events e
                WHERE e.event = '$pageview'
            """
        )

        compare_operators = EventsSessionWhereClauseTraverser(query, self.context).compare_operators

        assert len(compare_operators) == 1
        assert compare_operators[0] == ast.CompareOperation(
            left=ast.Field(chain=["event"]), op=ast.CompareOperationOp.Eq, right=ast.Constant(value="$pageview")
        )

    def test_with_multiple_clauses(self):
        query = self._select(
            """
                SELECT event
                FROM events
                WHERE event = '$pageview' AND timestamp > '2023-01-01'
            """
        )

        compare_operators = EventsSessionWhereClauseTraverser(query, self.context).compare_operators

        assert len(compare_operators) == 2
        assert compare_operators[0] == ast.CompareOperation(
            left=ast.Field(chain=["event"]), op=ast.CompareOperationOp.Eq, right=ast.Constant(value="$pageview")
        )
        assert compare_operators[1] == ast.CompareOperation(
            left=ast.Field(chain=["timestamp"]), op=ast.CompareOperationOp.Gt, right=ast.Constant(value="2023-01-01")
        )

    def test_with_join(self):
        query = self._select(
            """
                SELECT e.event, p.id
                FROM events e
                LEFT JOIN persons p
                ON e.person_id = p.id
                WHERE e.event = '$pageview' and p.is_identified = 0
            """
        )

        compare_operators = EventsSessionWhereClauseTraverser(query, self.context).compare_operators

        assert len(compare_operators) == 1
        assert compare_operators[0] == ast.CompareOperation(
            left=ast.Field(chain=["event"]), op=ast.CompareOperationOp.Eq, right=ast.Constant(value="$pageview")
        )
