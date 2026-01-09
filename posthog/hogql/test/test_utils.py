from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
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
