"""Documented divergences where the C++ ANTLR parser misbehaves and the Rust hand-roll is correct.

Each test asserts the *eventual* desired behaviour — typically that both backends produce the same AST.
Today the C++ side diverges, so the assertion fails and the test is decorated `@unittest.expectedFailure`.
When the C++ parser is fixed and the assertion passes, pytest reports XPASS — which becomes a failure
under `unittest`'s `expectedFailure` semantics — and that's the signal to delete the xfail test and
verify cpp matches rust.

Keep one test per cpp bug. Each test's docstring explains:

  1. What the source string is.
  2. What C++ currently does (the bug).
  3. What Rust does (the correct behaviour).
  4. Why C++ is wrong (grammar / visitor reference).

For Rust-correctness regression tests (where Rust used to be wrong and we fixed it), see the
parity-regression tests in `_test_parser.py`. This file is the inverse: regressions for *C++* whose
AST the Rust port deliberately does not bug-match.
"""

import unittest
from posthog.test.base import BaseTest

from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import clear_locations


class TestParserCppBugXfails(BaseTest):
    maxDiff = None

    @unittest.expectedFailure
    def test_sample_after_unpivot_on_join_expr_parens(self):
        # `select 1 from (a positional join b) unpivot (m for n in (o)) sample 0.5`
        # cpp: silently drops the trailing `SAMPLE 0.5`. ANTLR parses cleanly — the grammar admits
        #      `sampleClause` in three positions: at joinExpr level via `JoinExprTable: tableExpr FINAL?
        #      sampleClause?` (alt 124) and at selectStmt level via `(USING? sampleClause)?` (HogQLParser.g4
        #      lines 75 and 79). For this input, `(a positional join b)` is a JoinExprParens (alt 125), then
        #      `JoinExprUnpivot` (alt 123) wraps it — that's a joinExpr, not a tableExpr, so the SAMPLE
        #      lands at the selectStmt slot instead. The bug is in the visitor: `VISIT(SelectStmt)` in
        #      `parser_json.cpp` never calls `ctx->sampleClause()`, so the parsed SAMPLE subtree is
        #      silently dropped from the emitted JSON. The only `ctx->sampleClause()` call in the whole
        #      visitor is inside `VISIT(JoinExprTable)` (joinExpr-level only).
        # rust: attaches the SAMPLE to the outer JoinExpr's `.sample` field, preserving the user's
        #       SAMPLE intent. When cpp's `VISIT(SelectStmt)` is taught to visit `ctx->sampleClause()`
        #       (follow-up), both backends will agree on a shape (either rust's or a third-place
        #       attachment) and this test starts XPASSing — that's the signal to delete it.
        q = "select 1 from (a positional join b) unpivot (m for n in (o)) sample 0.5"
        cpp_ast = clear_locations(parse_select(q, backend="cpp-json"))
        rust_ast = clear_locations(parse_select(q, backend="rust-json"))
        self.assertEqual(cpp_ast, rust_ast)
