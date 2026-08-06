from posthog.test.base import BaseTest
from unittest import TestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.hogql.utils import deserialize_hx_ast, ilike_matches, like_matches


class TestIlikeMatches(BaseTest):
    @parameterized.expand(
        [
            # Basic wildcard tests
            ("%", "anything", True),
            ("%", "", True),
            ("%%", "anything", True),
            ("%%%%", "", True),
            ("_", "a", True),
            ("_", "ab", False),
            ("_", "", False),
            ("__", "ab", True),
            ("__", "a", False),
            ("____", "null", True),
            ("____", "nul", False),
            # Literal matching (no wildcards)
            ("hello", "hello", True),
            ("hello", "Hello", True),  # case insensitive
            ("hello", "HELLO", True),
            ("hello", "world", False),
            ("hello", "hello!", False),
            ("", "", True),
            ("", "a", False),
            # % wildcard - matches any sequence including empty
            ("%hello", "hello", True),
            ("%hello", "say hello", True),
            ("%hello", "hello world", False),
            ("hello%", "hello", True),
            ("hello%", "hello world", True),
            ("hello%", "say hello", False),
            ("%hello%", "hello", True),
            ("%hello%", "say hello world", True),
            ("%hello%", "helo", False),
            # _ wildcard - matches exactly one character
            ("h_llo", "hello", True),
            ("h_llo", "hallo", True),
            ("h_llo", "hllo", False),
            ("h_llo", "heello", False),
            ("_ello", "hello", True),
            ("_ello", "ello", False),
            ("hell_", "hello", True),
            ("hell_", "hell", False),
            # Combined wildcards
            ("%_", "a", True),
            ("%_", "", False),
            ("_%", "a", True),
            ("_%", "", False),
            ("%_%", "a", True),
            ("%_%", "", False),
            ("_%_", "ab", True),
            ("_%_", "a", False),
            ("%__%", "ab", True),
            ("%__%", "a", False),
            # Pattern at boundaries
            ("a%", "a", True),
            ("a%", "abc", True),
            ("a%", "ba", False),
            ("%a", "a", True),
            ("%a", "cba", True),
            ("%a", "ab", False),
            # Multiple % wildcards
            ("%a%b%", "ab", True),
            ("%a%b%", "aXb", True),
            ("%a%b%", "XaXbX", True),
            ("%a%b%", "ba", False),
            ("%a%b%c%", "abc", True),
            ("%a%b%c%", "aXbYc", True),
            # Case insensitivity edge cases
            ("%NULL%", "null", True),
            ("%null%", "NULL", True),
            ("%NuLl%", "nUlL", True),
            # Sentinel value tests (critical for optimization)
            ("%", "null", True),
            ("%", "", True),
            ("null", "null", True),
            ("null", "", False),
            ("%null%", "null", True),
            ("%null%", "nullable", True),
            ("%null%", "", False),
            ("%nu%", "null", True),
            ("%ul%", "null", True),
            ("%ll%", "null", True),
            ("n%", "null", True),
            ("%l", "null", True),
            ("%un%", "null", False),  # "null" doesn't contain "un"
            # Special characters (should match literally when not wildcards)
            ("a.b", "a.b", True),
            ("a.b", "aXb", False),
            ("a*b", "a*b", True),
            ("a*b", "aXb", False),
            ("a+b", "a+b", True),
            ("a?b", "a?b", True),
            ("a[b", "a[b", True),
            ("a]b", "a]b", True),
            ("a(b", "a(b", True),
            ("a)b", "a)b", True),
            ("a^b", "a^b", True),
            ("a$b", "a$b", True),
            ("a|b", "a|b", True),
            ("a{b", "a{b", True),
            ("a}b", "a}b", True),
            # Escape sequences - backslash escapes %, _, and \
            ("100\\%", "100%", True),
            ("100\\%", "100", False),
            ("100\\%", "1000", False),
            ("a\\_b", "a_b", True),
            ("a\\_b", "aXb", False),
            ("a\\\\b", "a\\b", True),
            ("a\\\\b", "ab", False),
            # Escape sequences with wildcards
            ("\\%%", "%", True),
            ("\\%%", "%anything", True),
            ("\\%%", "anything", False),
            ("%\\%", "100%", True),
            ("%\\%", "100", False),
            ("\\_%", "_", True),
            ("\\_%", "_anything", True),
            ("\\_%", "anything", False),
            # UTF-8 handling - _ should match one Unicode code point
            ("_", "¥", True),  # ¥ is one code point (2 bytes in UTF-8)
            ("_", "中", True),  # Chinese character is one code point
            ("__", "中文", True),  # Two Chinese characters
            ("%中%", "你好中文世界", True),
            ("__", "¥", False),  # two bytes but only one code point
            # Newline handling - % and _ should match newlines
            ("%", "hello\nworld", True),
            ("_", "\n", True),
            ("a%b", "a\nb", True),
            ("a_b", "a\nb", True),
            ("hello%world", "hello\nworld", True),
            ("%\n%", "line1\nline2", True),
            # Edge cases with consecutive wildcards
            ("%%a%%", "a", True),
            ("%%a%%", "XXaXX", True),
            ("_%_%", "ab", True),
            ("_%_%", "abc", True),
            ("_%_%", "a", False),
        ]
    )
    def test_ilike_matches_against_clickhouse(self, pattern: str, text: str, expected: bool) -> None:
        # Run actual ClickHouse query
        result = execute_hogql_query(
            team=self.team,
            query="SELECT ilike({text}, {pattern})",
            placeholders={"text": ast.Constant(value=text), "pattern": ast.Constant(value=pattern)},
        )
        clickhouse_result = result.results[0][0] == 1

        # Verify our expectation matches ClickHouse
        self.assertEqual(
            clickhouse_result,
            expected,
            f"ClickHouse ilike({text!r}, {pattern!r}) returned {clickhouse_result}, expected {expected}",
        )

        # Verify our Python implementation matches ClickHouse
        python_result = ilike_matches(pattern, text)

        self.assertEqual(
            python_result,
            clickhouse_result,
            f"Python ilike_matches({pattern!r}, {text!r}) returned {python_result}, "
            f"but ClickHouse returned {clickhouse_result}",
        )


class TestLikeMatches(BaseTest):
    @parameterized.expand(
        [
            # Basic wildcard tests
            ("%", "anything", True),
            ("%", "", True),
            ("%%", "anything", True),
            ("%%%%", "", True),
            ("_", "a", True),
            ("_", "ab", False),
            ("_", "", False),
            ("__", "ab", True),
            ("__", "a", False),
            ("____", "null", True),
            ("____", "nul", False),
            # Literal matching (no wildcards) - CASE SENSITIVE
            ("hello", "hello", True),
            ("hello", "Hello", False),  # case sensitive - differs from ILIKE
            ("hello", "HELLO", False),  # case sensitive - differs from ILIKE
            ("Hello", "Hello", True),
            ("HELLO", "HELLO", True),
            ("hello", "world", False),
            ("hello", "hello!", False),
            ("", "", True),
            ("", "a", False),
            # % wildcard - matches any sequence including empty
            ("%hello", "hello", True),
            ("%hello", "say hello", True),
            ("%hello", "Hello", False),  # case sensitive
            ("%hello", "hello world", False),
            ("hello%", "hello", True),
            ("hello%", "hello world", True),
            ("hello%", "say hello", False),
            ("%hello%", "hello", True),
            ("%hello%", "say hello world", True),
            ("%hello%", "helo", False),
            # _ wildcard - matches exactly one character
            ("h_llo", "hello", True),
            ("h_llo", "hallo", True),
            ("h_llo", "hllo", False),
            ("h_llo", "heello", False),
            ("_ello", "hello", True),
            ("_ello", "ello", False),
            ("hell_", "hello", True),
            ("hell_", "hell", False),
            # Combined wildcards
            ("%_", "a", True),
            ("%_", "", False),
            ("_%", "a", True),
            ("_%", "", False),
            ("%_%", "a", True),
            ("%_%", "", False),
            ("_%_", "ab", True),
            ("_%_", "a", False),
            ("%__%", "ab", True),
            ("%__%", "a", False),
            # Pattern at boundaries
            ("a%", "a", True),
            ("a%", "abc", True),
            ("a%", "ba", False),
            ("A%", "abc", False),  # case sensitive
            ("%a", "a", True),
            ("%a", "cba", True),
            ("%a", "ab", False),
            # Multiple % wildcards
            ("%a%b%", "ab", True),
            ("%a%b%", "aXb", True),
            ("%a%b%", "XaXbX", True),
            ("%a%b%", "ba", False),
            ("%a%b%c%", "abc", True),
            ("%a%b%c%", "aXbYc", True),
            # Case sensitivity tests - KEY DIFFERENCE FROM ILIKE
            ("%NULL%", "null", False),  # case sensitive - differs from ILIKE
            ("%null%", "NULL", False),  # case sensitive - differs from ILIKE
            ("%NuLl%", "nUlL", False),  # case sensitive - differs from ILIKE
            ("%NULL%", "NULL", True),
            ("%null%", "null", True),
            # Sentinel value tests (critical for optimization)
            ("%", "null", True),
            ("%", "", True),
            ("null", "null", True),
            ("null", "NULL", False),  # case sensitive
            ("null", "", False),
            ("%null%", "null", True),
            ("%null%", "nullable", True),
            ("%null%", "", False),
            ("%nu%", "null", True),
            ("%ul%", "null", True),
            ("%ll%", "null", True),
            ("n%", "null", True),
            ("%l", "null", True),
            ("%un%", "null", False),  # "null" doesn't contain "un"
            # Special characters (should match literally when not wildcards)
            ("a.b", "a.b", True),
            ("a.b", "aXb", False),
            ("a*b", "a*b", True),
            ("a*b", "aXb", False),
            ("a+b", "a+b", True),
            ("a?b", "a?b", True),
            ("a[b", "a[b", True),
            ("a]b", "a]b", True),
            ("a(b", "a(b", True),
            ("a)b", "a)b", True),
            ("a^b", "a^b", True),
            ("a$b", "a$b", True),
            ("a|b", "a|b", True),
            ("a{b", "a{b", True),
            ("a}b", "a}b", True),
            # Escape sequences - backslash escapes %, _, and \
            ("100\\%", "100%", True),
            ("100\\%", "100", False),
            ("100\\%", "1000", False),
            ("a\\_b", "a_b", True),
            ("a\\_b", "aXb", False),
            ("a\\\\b", "a\\b", True),
            ("a\\\\b", "ab", False),
            # Escape sequences with wildcards
            ("\\%%", "%", True),
            ("\\%%", "%anything", True),
            ("\\%%", "anything", False),
            ("%\\%", "100%", True),
            ("%\\%", "100", False),
            ("\\_%", "_", True),
            ("\\_%", "_anything", True),
            ("\\_%", "anything", False),
            # UTF-8 handling - _ should match one Unicode code point
            ("_", "¥", True),
            ("_", "中", True),
            ("__", "中文", True),
            ("%中%", "你好中文世界", True),
            ("__", "¥", False),  # two bytes but only one code point
            # Newline handling - % and _ should match newlines
            ("%", "hello\nworld", True),
            ("_", "\n", True),
            ("a%b", "a\nb", True),
            ("a_b", "a\nb", True),
            ("hello%world", "hello\nworld", True),
            ("%\n%", "line1\nline2", True),
            # Edge cases with consecutive wildcards
            ("%%a%%", "a", True),
            ("%%a%%", "XXaXX", True),
            ("_%_%", "ab", True),
            ("_%_%", "abc", True),
            ("_%_%", "a", False),
        ]
    )
    def test_like_matches_against_clickhouse(self, pattern: str, text: str, expected: bool) -> None:
        result = execute_hogql_query(
            team=self.team,
            query="SELECT like({text}, {pattern})",
            placeholders={"text": ast.Constant(value=text), "pattern": ast.Constant(value=pattern)},
        )
        clickhouse_result = result.results[0][0] == 1

        self.assertEqual(
            clickhouse_result,
            expected,
            f"ClickHouse like({text!r}, {pattern!r}) returned {clickhouse_result}, expected {expected}",
        )

        python_result = like_matches(pattern, text)

        self.assertEqual(
            python_result,
            clickhouse_result,
            f"Python like_matches({pattern!r}, {text!r}) returned {python_result}, "
            f"but ClickHouse returned {clickhouse_result}",
        )


class TestUtils(BaseTest):
    @parameterized.expand(
        [
            ("JOIN",),
            ("INNER",),
            ("INNER JOIN",),
            ("LEFT JOIN",),
            ("LEFT OUTER JOIN",),
            ("RIGHT ANY JOIN",),
            ("ASOF LEFT JOIN",),
            ("GLOBAL LEFT JOIN",),
        ]
    )
    def test_deserialize_hx_ast_allows_valid_join_types(self, join_type: str) -> None:
        join_expr = deserialize_hx_ast(
            {
                "__hx_ast": "JoinExpr",
                "join_type": join_type,
                "table": {"__hx_ast": "Field", "chain": ["events"]},
            }
        )

        assert isinstance(join_expr, ast.JoinExpr)
        self.assertEqual(join_expr.join_type, join_type)

    @parameterized.expand(
        [
            ("JOIN; SELECT 1",),
            ("LEFT JOIN SETTINGS max_threads=1",),
            ("GLOBAL JOIN; DROP TABLE events",),
        ]
    )
    def test_deserialize_hx_ast_rejects_invalid_join_types(self, join_type: str) -> None:
        with self.assertRaises(ValueError) as e:
            deserialize_hx_ast(
                {
                    "__hx_ast": "JoinExpr",
                    "join_type": join_type,
                    "table": {"__hx_ast": "Field", "chain": ["events"]},
                }
            )

        self.assertEqual(str(e.exception), f"Invalid join type: {join_type}")

    @parameterized.expand(
        [
            ("ON",),
            ("USING",),
        ]
    )
    def test_deserialize_hx_ast_allows_valid_join_constraint_type(self, constraint_type: str) -> None:
        join_constraint = deserialize_hx_ast(
            {
                "__hx_ast": "JoinConstraint",
                "expr": {"__hx_ast": "Constant", "value": 1},
                "constraint_type": constraint_type,
            }
        )

        assert isinstance(join_constraint, ast.JoinConstraint)
        self.assertEqual(join_constraint.constraint_type, constraint_type)

    @parameterized.expand(
        [
            ("ON; SELECT 1",),
            ("USING SETTINGS",),
        ]
    )
    def test_deserialize_hx_ast_rejects_invalid_join_constraint_type(self, constraint_type: str) -> None:
        with self.assertRaises(ValueError) as e:
            deserialize_hx_ast(
                {
                    "__hx_ast": "JoinConstraint",
                    "expr": {"__hx_ast": "Constant", "value": 1},
                    "constraint_type": constraint_type,
                }
            )

        self.assertEqual(str(e.exception), f"Invalid join constraint type: {constraint_type}")

    def test_deserialize_hx_ast(self):
        assert deserialize_hx_ast(
            {
                "__hx_ast": "Constant",
                "value": 1,
            }
        ) == ast.Constant(value=1)

        assert deserialize_hx_ast(
            {
                "__hx_ast": "Call",
                "name": "hello",
                "args": [
                    {
                        "__hx_ast": "Constant",
                        "value": "is it me?",
                    }
                ],
            }
        ) == ast.Call(name="hello", args=[ast.Constant(value="is it me?")])

        assert deserialize_hx_ast(
            {
                "__hx_ast": "SelectQuery",
                "group_by": [{"__hx_ast": "Field", "chain": ["event"]}],
                "select": [
                    {"__hx_tag": "blink", "children": [{"__hx_ast": "Field", "chain": ["event"]}]},
                    {
                        "__hx_ast": "Call",
                        "args": [{"__hx_ast": "Field", "chain": ["*"]}],
                        "distinct": False,
                        "name": "count",
                    },
                    "ewrew222",
                ],
                "select_from": {"__hx_ast": "JoinExpr", "table": {"__hx_ast": "Field", "chain": ["events"]}},
                "where": {
                    "__hx_ast": "CompareOperation",
                    "left": {"__hx_ast": "Field", "chain": ["timestamp"]},
                    "op": ">",
                    "right": {
                        "__hx_ast": "ArithmeticOperation",
                        "left": {"__hx_ast": "Call", "args": [], "distinct": False, "name": "now"},
                        "op": "-",
                        "right": {
                            "__hx_ast": "Call",
                            "args": [{"__hx_ast": "Constant", "value": 1}],
                            "distinct": False,
                            "name": "toIntervalDay",
                        },
                    },
                },
            }
        ) == ast.SelectQuery(
            select=[
                ast.HogQLXTag(
                    kind="blink", attributes=[ast.HogQLXAttribute(name="children", value=[ast.Field(chain=["event"])])]
                ),
                ast.Call(name="count", args=[ast.Field(chain=["*"])]),
                ast.Constant(value="ewrew222"),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                right=ast.ArithmeticOperation(
                    left=ast.Call(name="now", args=[]),
                    right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)]),
                    op=ast.ArithmeticOperationOp.Sub,
                ),
                op=ast.CompareOperationOp.Gt,
            ),
            group_by=[ast.Field(chain=["event"])],
        )

    def test_deserialize_hx_ast_error(self):
        with self.assertRaises(ValueError) as e:
            deserialize_hx_ast(
                {
                    "__hx_ast": "Constant",
                    "value": 1,
                    "unexpected": 2,
                }
            )
        self.assertEqual(str(e.exception), "Unexpected field 'unexpected' for AST node 'Constant'")

        with self.assertRaises(ValueError) as e:
            deserialize_hx_ast(
                {
                    "__hx_ast": "Invalid",
                    "value": 1,
                }
            )
        self.assertEqual(str(e.exception), "Invalid or missing '__hx_ast' kind: Invalid")


class TestPrettyPrintInTests(TestCase):
    @parameterized.expand(
        [
            (
                "prewhere_stays_intact",
                "SELECT 1 FROM events PREWHERE x WHERE y",
                ["\nPREWHERE x", "\nWHERE y", "\nSELECT 1", "\nFROM events"],
                ["PRE\nWHERE"],
            ),
            (
                "all_top_level_keywords_split",
                "SELECT a FROM t WHERE b GROUP BY c HAVING d QUALIFY q WINDOW w ORDER BY e LIMIT 1 OFFSET 2 SETTINGS x = 1",
                [
                    "\nSELECT a",
                    "\nFROM t",
                    "\nWHERE b",
                    "\nGROUP BY",
                    "\nHAVING d",
                    "\nQUALIFY q",
                    "\nWINDOW w",
                    "\nORDER BY e",
                    "\nLIMIT 1",
                    "\nOFFSET 2",
                    "\nSETTINGS x = 1",
                ],
                ["PRE\nWHERE"],
            ),
            (
                "keyword_substring_of_token_not_split",
                "SELECT 1 FROM UNLIMITED",
                ["\nFROM UNLIMITED"],
                ["UN\nLIMITED", "\nLIMITED", "\nLIMIT"],
            ),
            (
                "keyword_already_at_line_start_not_doubled",
                "SELECT a\n    FROM t\n    WHERE b\n    ORDER BY c",
                ["\nFROM t", "\nWHERE b", "\nORDER BY c"],
                ["\n    \nFROM", "\n    \nWHERE", "\n    \nORDER", "\n\nFROM"],
            ),
            (
                "keyword_at_line_start_no_indent_not_doubled",
                "SELECT a\nFROM t\nWHERE b",
                ["SELECT a\nFROM t\nWHERE b"],
                ["\n\nFROM", "\n\nWHERE"],
            ),
        ]
    )
    def test_keyword_newline_insertion(self, _name: str, query: str, present: list[str], absent: list[str]) -> None:
        result = pretty_print_in_tests(query, 1)
        for fragment in present:
            self.assertIn(fragment, result)
        for fragment in absent:
            self.assertNotIn(fragment, result)

    @parameterized.expand(
        [
            (
                "nested_subquery_indents_deeper_than_outer",
                "FROM (SELECT x FROM (SELECT y FROM z) AS inner) AS outer",
                ["\nFROM (", "\n  SELECT x", "\n  FROM (", "\n    SELECT y", "\n    FROM z) AS inner) AS outer"],
                ["\n  SELECT y", "\nSELECT x"],
            ),
            (
                "line_starting_with_closing_bracket_dedents",
                "FROM (SELECT b\n) AS e LIMIT 1",
                ["\nFROM (", "\n  SELECT b", "\n) AS e", "\nLIMIT 1"],
                ["\n  ) AS e", "\n    SELECT b"],
            ),
            (
                "sibling_subqueries_each_indent_under_their_own_bracket",
                "FROM (SELECT a FROM x) AS p, (SELECT b FROM y) AS q",
                ["\nFROM (", "\n  SELECT a", "\n  FROM x) AS p, (", "\n  SELECT b", "\n  FROM y) AS q"],
                ["\n    SELECT a", "\n    SELECT b"],
            ),
            (
                "brackets_inside_string_literal_do_not_shift_depth",
                "SELECT a FROM events WHERE x = '(' GROUP BY a",
                ["\nSELECT a", "\nFROM events", "\nWHERE x = '('", "\nGROUP BY a"],
                ["\n  GROUP BY a", "\n  WHERE"],
            ),
            (
                "continuation_lines_indent_under_their_clause_keyword",
                "-- ClickHouse\nSELECT\n  e.event AS event\nFROM\n  events AS e",
                ["-- ClickHouse", "\nSELECT", "\n  e.event AS event", "\nFROM", "\n  events AS e"],
                ["\n  SELECT", "\n  FROM", "\nevents AS e", "  -- ClickHouse"],
            ),
            (
                "with_clause_anchors_at_column_zero_and_body_indents",
                "WITH a AS (SELECT 1) SELECT b FROM c",
                ["WITH a AS (", "\n  SELECT 1)", "\nSELECT b", "\nFROM c"],
                ["\n  WITH", "\n  SELECT b"],
            ),
            (
                "bracket_started_line_is_not_indented_as_a_continuation",
                "[['a', (0, None)], ['b', (1, None)]]",
                ["[['a', (0, None)], ['b', (1, None)]]"],
                ["  [['a'"],
            ),
        ]
    )
    def test_bracket_depth_indentation(self, _name: str, query: str, present: list[str], absent: list[str]) -> None:
        result = pretty_print_in_tests(query, 1)
        for fragment in present:
            self.assertIn(fragment, result)
        for fragment in absent:
            self.assertNotIn(fragment, result)

    def test_normalizes_team_id(self) -> None:
        result = pretty_print_in_tests("WHERE equals(events.team_id, 99999)", 99999)
        self.assertIn("team_id, 420)", result)
        self.assertNotIn("99999", result)

    def test_none_query_returns_empty_string(self) -> None:
        self.assertEqual(pretty_print_in_tests(None, 1), "")
