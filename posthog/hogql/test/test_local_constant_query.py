from unittest import TestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.local_constant_query import LocalQueryResult, try_execute_local_constant_query
from posthog.hogql.parser import parse_select


class TestLocalConstantQuery(TestCase):
    @parameterized.expand(
        [
            (
                "scalar literals",
                "SELECT 1, -129, 1.5, 'hello', NULL, true, false",
                ["one", "negative", "float", "text", "null", "true", "false"],
                LocalQueryResult(
                    results=[(1, -129, 1.5, "hello", None, 1, 0)],
                    types=[
                        ("one", "UInt8"),
                        ("negative", "Int16"),
                        ("float", "Float64"),
                        ("text", "String"),
                        ("null", "Nullable(Nothing)"),
                        ("true", "UInt8"),
                        ("false", "UInt8"),
                    ],
                ),
            ),
            (
                "aliases and containers",
                "SELECT [1, 256, NULL] AS numbers, (1, 'hello') AS pair, [] AS empty",
                ["numbers", "pair", "empty"],
                LocalQueryResult(
                    results=[([1, 256, None], (1, "hello"), [])],
                    types=[
                        ("numbers", "Array(Nullable(UInt16))"),
                        ("pair", "Tuple(UInt8, String)"),
                        ("empty", "Array(Nothing)"),
                    ],
                ),
            ),
            (
                "false where",
                "SELECT 1 WHERE false",
                ["one"],
                LocalQueryResult(results=[], types=[("one", "UInt8")]),
            ),
            (
                "zero limit",
                "SELECT 1 LIMIT 0",
                ["one"],
                LocalQueryResult(results=[], types=[("one", "UInt8")]),
            ),
            (
                "positive offset",
                "SELECT 1 OFFSET 1",
                ["one"],
                LocalQueryResult(results=[], types=[("one", "UInt8")]),
            ),
        ]
    )
    def test_executes_supported_query(
        self,
        _name: str,
        query: str,
        columns: list[str],
        expected: LocalQueryResult,
    ) -> None:
        parsed_query = parse_select(query)
        assert isinstance(parsed_query, ast.SelectQuery)

        self.assertEqual(try_execute_local_constant_query(parsed_query, columns), expected)

    @parameterized.expand(
        [
            ("arithmetic", "SELECT 1 + 1"),
            ("function", "SELECT upper('hello')"),
            ("table", "SELECT 1 FROM events"),
            ("distinct", "SELECT DISTINCT 1"),
            ("ordering", "SELECT 1 ORDER BY 1"),
            ("invalid filter type", "SELECT 1 WHERE -1"),
            ("mixed numeric array", "SELECT [1, 2.5]"),
        ]
    )
    def test_returns_none_for_unsupported_query(self, _name: str, query: str) -> None:
        parsed_query = parse_select(query)
        assert isinstance(parsed_query, ast.SelectQuery)

        self.assertIsNone(try_execute_local_constant_query(parsed_query, ["result"]))
