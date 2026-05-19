"""Reduced regressions for HogQL parser-parity bugs.

Each test pins a discrepancy that was found between the parser
backends and then fixed. Every case runs against all three backends
(`cpp-json`, `rust-json`, `python`) explicitly, so a regression on any
one is caught.

Unlike the `parser_test_factory` suite in `_test_parser.py`, this file
uses a plain `BaseTest` — no `MemoryLeakTestMixin`. The leak mixin
re-runs each test ~100x and measures incremental memory; an
assertion that parses input which *raises* (with C++'s verbose
`extraneous input … expecting {…}` message) trips its noise-sensitive
ratio check intermittently. Running each backend once here avoids that.
"""

from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_expr

_BACKENDS = ("cpp-json", "rust-json", "python")

# The eight Hog-statement keywords. They head a `statement` and are
# omitted from the grammar's `keyword` rule, so they are not valid
# `identifier`s / Field names in expression position.
_STATEMENT_KEYWORDS = ("fn", "fun", "let", "while", "throw", "try", "catch", "finally")


class TestParserRegressions(BaseTest):
    maxDiff = None

    def test_statement_keywords_rejected_as_expressions(self):
        # `fn`, `let`, `while`, … cannot stand as a Field or call head
        # in an expression (unlike `if` / `for` / `return`, which the
        # `keyword` rule does include).
        for backend in _BACKENDS:
            for kw in _STATEMENT_KEYWORDS:
                with self.assertRaises(ExposedHogQLError, msg=f"{backend}: {kw!r} should reject"):
                    parse_expr(kw, backend=backend)

    def test_exponent_float_without_fractional_digits(self):
        # `1.e5` is one FLOATING_LITERAL token in the grammar
        # (`DECIMAL_LITERAL DOT DEC_DIGIT* E (PLUS|DASH)? DEC_DIGIT+`),
        # i.e. the fractional digits are optional. The Rust lexer used
        # to stop at the `.` and let the Pratt postfix loop fold
        # `1.e5` into `ArrayAccess(Constant(1), Constant('e5'))`.
        cases = {
            "1.e5": 100000.0,
            "1.E5": 100000.0,
            "1.e+5": 100000.0,
            "1.e-5": 1e-05,
            "12.e2": 1200.0,
        }
        for backend in _BACKENDS:
            for src, expected in cases.items():
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.Constant, msg=f"{backend}: {src!r}")
                self.assertEqual(node.value, expected, msg=f"{backend}: {src!r}")
