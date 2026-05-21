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
        # cpp: silently drops the trailing `SAMPLE 0.5` — `select_from.sample = None` and no top-level
        #      `sample` key. The grammar's `JoinExprTable: tableExpr (FINAL | sampleClause)*` requires
        #      a tableExpr, but `(joinExpr)` is a `JoinExprParens` (a joinExpr alt, not a tableExpr);
        #      cpp's visitor accepts the input and emits a `SelectQuery` with the SAMPLE missing.
        # rust: attaches the SAMPLE to the outer JoinExpr's `.sample` field, preserving the user's
        #       SAMPLE intent. Either rust's "attach" or a hard reject is acceptable; silently
        #       dropping it (cpp) is the bug. When cpp is fixed (this PR's scope leaves it for a
        #       follow-up), both backends will agree and this test starts XPASSing.
        q = "select 1 from (a positional join b) unpivot (m for n in (o)) sample 0.5"
        cpp_ast = clear_locations(parse_select(q, backend="cpp-json"))
        rust_ast = clear_locations(parse_select(q, backend="rust-json"))
        self.assertEqual(cpp_ast, rust_ast)
