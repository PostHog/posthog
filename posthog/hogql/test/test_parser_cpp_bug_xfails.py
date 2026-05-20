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

Currently empty — all five original cpp-side monsters resolved:
  - HOGQLX block-comment phantom attribute → grammar lexer fix
  - HOGQLX `--` line-comment phantom attribute → grammar lexer fix
  - HOGQLX `#` unrecognised character → grammar UNEXPECTED_CHARACTER catch-all
  - Float subnormal underflow → cpp `strtod` + errno fix
  - Hog `*= 2` (parser-level) → rust stmt-rhs Pratt-failure recovery
"""

from posthog.test.base import BaseTest


class TestParserCppBugXfails(BaseTest):
    pass
