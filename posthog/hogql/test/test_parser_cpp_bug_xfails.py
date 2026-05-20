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
    def test_hogqlx_block_comment_phantom_attribute(self):
        """`<a /*c*/ b={1}/>` — C++ emits a phantom `c` boolean attribute.

        C++ HOGQLX-mode lexer doesn't skip block comments between
        attributes; it tokenises the comment's word content as an
        attribute name. Rust ignores the comment and produces only
        the real `b={1}` attribute. Same bug pattern fires for:

          - `<a /*c d*/ /\>` → cpp emits both `c` and `d` as phantom attrs
          - `<a /* c */b={1}/>` → cpp renames `b` to `c`
        """
        src = "<a /*c*/ b={1}/>"
        cpp_ast = clear_locations(parse_expr(src, backend="cpp-json"))
        rust_ast = clear_locations(parse_expr(src, backend="rust-json"))
        self.assertEqual(cpp_ast, rust_ast)

    @unittest.expectedFailure
    def test_hogqlx_dash_dash_line_comment_phantom_attribute(self):
        """`<a -- comment\\n />` — C++ emits a phantom `comment` attribute.

        Same root cause as the block-comment case: the HOGQLX-mode
        lexer doesn't recognise `--` line comments and tokenises the
        identifier-shaped content as an attribute name. Rust correctly
        rejects the `-` token in the attribute slot.
        """
        src = "<a -- comment\n />"
        cpp_ast = clear_locations(parse_expr(src, backend="cpp-json"))
        rust_ast = clear_locations(parse_expr(src, backend="rust-json"))
        self.assertEqual(cpp_ast, rust_ast)

    @unittest.expectedFailure
    def test_hogqlx_hash_line_comment_phantom_attribute(self):
        """`<a # comment\\n />` — C++ accepts as if `#` opens a line
        comment but the lexer then re-tokenises `comment` as an
        attribute name. Rust correctly rejects `#` in HOGQLX attribute
        position.
        """
        src = "<a # comment\n />"
        cpp_ast = clear_locations(parse_expr(src, backend="cpp-json"))
        rust_ast = clear_locations(parse_expr(src, backend="rust-json"))
        self.assertEqual(cpp_ast, rust_ast)

    @unittest.expectedFailure
    def test_float_subnormal_underflow_emits_infinity(self):
        """`1e-310` — C++ emits `Constant(value="Infinity", value_type="number")`.

        C++ likely mishandles `errno==ERANGE` from `std::stod`: an
        underflow result (which `strtod` reports with a valid
        subnormal return value AND `errno = ERANGE`) is treated the
        same as overflow, flattened to `"Infinity"`. Rust uses
        `parse::<f64>()` which never errors on subnormals.

        Boundary observed:
          - `1e-308` → both: `1e-308`
          - `1e-310 .. 5e-324` → cpp: `"Infinity"`, rust: actual value
          - `1e-325` and below → cpp: `"Infinity"`, rust: `0.0`
          - `1e1000` and overflow → both: `"Infinity"` (matches)

        Same divergence for the negative-exponent (`-1e-400`).
        """
        src = "1e-310"
        cpp_raw = json.loads(cpp.parse_expr_json(src))
        rust_raw = json.loads(hogql_parser_rs.parse_expr_json(src))
        self.assertEqual(_strip(cpp_raw), _strip(rust_raw))

    @unittest.expectedFailure
    def test_hog_compound_assignment_op_garbage_recovery(self):
        """`let x := 1; x *= 2;` — C++ silently splits `x *= 2` into
        three nonsensical ExprStatements (`x`, then `* == 2`).

        C++'s ALL(*) error-recovery accepts the broken-token sequence
        as long as the surrounding declarations are parseable. The
        emitted AST is nonsense (`* == 2` has no semantic meaning),
        but the *parse* succeeds. Rust hard-errors with
        `unexpected token in expression: EqDouble` — the correct
        behaviour for a syntax error.

        Either both should reject (rust's current behaviour, ideal),
        or both should implement real compound-assignment desugaring
        (`x *= 2` → `x := x * 2`). Today neither side does the latter.
        """
        src = "let x := 1; x *= 2;"
        # Both should accept-and-desugar OR both should reject. Today
        # cpp accepts garbage and rust rejects, so assertEqual on the
        # parse result fails (rust raises before we can compare ASTs).
        cpp_ast = clear_locations(parse_program(src, backend="cpp-json"))
        rust_ast = clear_locations(parse_program(src, backend="rust-json"))
        self.assertEqual(cpp_ast, rust_ast)
