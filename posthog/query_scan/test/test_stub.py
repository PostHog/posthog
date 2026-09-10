from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import HogQLPrinter

from posthog.query_scan.stub import stub_in_subqueries


def print_hogql(node: ast.Expr) -> str:
    # HogQLPrinter serializes a parsed tree with no database, so the stub can be checked without one.
    return HogQLPrinter(context=HogQLContext(team_id=0)).visit(node)


class TestStubInSubqueries(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "IN a subquery",
                "SELECT count() FROM events WHERE event IN (SELECT event FROM events)",
                "SELECT count() FROM events WHERE 1",
                1,
            ),
            (
                "NOT IN a subquery",
                "SELECT count() FROM events WHERE event NOT IN (SELECT event FROM events)",
                "SELECT count() FROM events WHERE 1",
                1,
            ),
            (
                "NOT wrapping an IN subquery folds whole, never NOT 1",
                "SELECT count() FROM events WHERE NOT (event IN (SELECT event FROM events))",
                "SELECT count() FROM events WHERE 1",
                1,
            ),
            (
                "an IN subquery inside a JOIN subquery",
                "SELECT count() FROM events e "
                "JOIN (SELECT id FROM persons WHERE id IN (SELECT id FROM cohortpeople)) p ON e.person_id = p.id",
                "SELECT count() FROM events e JOIN (SELECT id FROM persons WHERE 1) p ON e.person_id = p.id",
                1,
            ),
            (
                "an IN subquery in the select list",
                "SELECT event IN (SELECT event FROM events) FROM events",
                "SELECT 1 FROM events",
                1,
            ),
            (
                "a literal IN list survives",
                "SELECT count() FROM events WHERE event IN ('$pageview', '$autocapture')",
                "SELECT count() FROM events WHERE event IN ('$pageview', '$autocapture')",
                0,
            ),
        ]
    )
    def test_stub_replaces_in_subqueries_and_keeps_literal_lists(
        self, _name: str, source: str, expected: str, expected_subqueries: int
    ) -> None:
        result = stub_in_subqueries(parse_select(source))

        self.assertEqual(print_hogql(result.stubbed), print_hogql(parse_select(expected)))
        self.assertEqual(len(result.subqueries), expected_subqueries)

    def test_global_in_is_stubbed_too(self) -> None:
        # HogQL has no GLOBAL IN syntax, so build the op the tree carries once it is lowered for a
        # distributed query.
        node = parse_select("SELECT count() FROM events WHERE event IN (SELECT event FROM events)")
        assert isinstance(node, ast.SelectQuery) and isinstance(node.where, ast.CompareOperation)
        node.where.op = ast.CompareOperationOp.GlobalIn

        result = stub_in_subqueries(node)

        self.assertEqual(len(result.subqueries), 1)
        self.assertEqual(print_hogql(result.stubbed), print_hogql(parse_select("SELECT count() FROM events WHERE 1")))

    def test_collector_returns_subqueries_in_visit_order(self) -> None:
        source = (
            "SELECT count() FROM events "
            "WHERE event IN (SELECT 'first' FROM events) AND event IN (SELECT 'second' FROM events)"
        )

        result = stub_in_subqueries(parse_select(source))

        self.assertEqual(len(result.subqueries), 2)
        printed = [print_hogql(subquery) for subquery in result.subqueries]
        self.assertIn("'first'", printed[0])
        self.assertIn("'second'", printed[1])
