"""Documented divergences where the C++ ANTLR parser misbehaves and
the Rust hand-roll is correct.

Each test asserts the *eventual* desired behaviour — typically that
both backends produce the same AST (or both reject / both accept).
Today the C++ side diverges, so the assertion fails and the test is
decorated `@unittest.expectedFailure`. When the C++ parser is fixed
and the assertion passes, pytest reports XPASS, which becomes a
failure under `unittest`'s `expectedFailure` semantics — that's the
signal to delete the xfail test and verify cpp matches rust.

Keep one test per cpp bug. Each test's docstring explains:

  1. What the source string is.
  2. What C++ currently does (the bug).
  3. What Rust does (the correct behaviour).
  4. Why C++ is wrong (grammar / lexer reference).

For Rust-correctness regression tests (where Rust used to be wrong and
we fixed it), see `test_parser_regressions.py`. This file is the
inverse: regressions for *C++* whose AST the Rust port deliberately
does not bug-match.
"""

import json
import unittest

import hogql_parser as cpp
import hogql_parser_rs

from posthog.hogql.visitor import clear_locations
from posthog.hogql.parser import parse_expr, parse_program
from posthog.test.base import BaseTest


def _strip(value):
    """Drop start/end and explicit None fields so AST trees compare on
    structure rather than serialiser-specific filler."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in ("start", "end"):
                continue
            if v is None:
                continue
            out[k] = _strip(v)
        return out
    if isinstance(value, list):
        return [_strip(x) for x in value]
    return value


class TestParserCppBugXfails(BaseTest):
    @unittest.expectedFailure
    def test_hog_compound_assignment_op_garbage_recovery(self):
        """`let x := 1; x *= 2;` — C++ silently splits `x *= 2` into
        three nonsensical ExprStatements (`x`, then `Compare(Field("*"),
        op="==", right=2)`). The other compound-assignment operators
        (`+=` / `-=` / `/=` / `%=`) all reject in cpp; only `*=` is
        recovered via ANTLR's automatic single-token-insertion
        (`*=` is read as `*` then `=`, then ANTLR inserts a missing
        second `=` to make the comparison operator `==`).

        Rust correctly rejects (`unexpected token in expression:
        EqDouble`). To resolve, cpp would need to disable ANTLR's
        token-insertion error recovery for this slot or add an
        explicit `*=` reject token — both are involved. The cleaner
        long-term fix is to implement compound assignment in both
        parsers (`x *= 2` → desugar to `x := x * 2`); meanwhile both
        rejecting is acceptable since no production query relies on
        the recovered AST.
        """
        src = "let x := 1; x *= 2;"
        # Both should accept-and-desugar OR both should reject. Today
        # cpp accepts garbage and rust rejects, so assertEqual on the
        # parse result fails (rust raises before we can compare ASTs).
        cpp_ast = clear_locations(parse_program(src, backend="cpp-json"))
        rust_ast = clear_locations(parse_program(src, backend="rust-json"))
        self.assertEqual(cpp_ast, rust_ast)
