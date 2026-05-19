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
from posthog.hogql.parser import parse_expr, parse_program, parse_select
from posthog.hogql.visitor import clear_locations

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

    def test_clause_keyword_after_comma_in_select_columns(self):
        # A clause keyword after the trailing comma starts its clause
        # when a valid body follows: `select a, where b` is one column
        # plus a WHERE clause, not two columns. With no body the
        # keyword stays a column: `select a, where` is two columns.
        # The Rust parser used to always keep it as a column.
        for backend in _BACKENDS:
            # clause keyword + body → trailing comma, clause starts.
            # `where * columns('x')` is also a valid multiplication
            # column, but cpp's ALL(*) prefers the clause; the Rust
            # parser used to keep the (valid) column interpretation.
            for src, attr in (
                ("select a, where b", "where"),
                ("select a, having b", "having"),
                ("select a, prewhere c", "prewhere"),
                ("select a, qualify d", "qualify"),
                ("select columns('gk'), where * columns('gk') with totals", "where"),
                ("select a, prewhere * columns('y')", "prewhere"),
            ):
                node = parse_select(src, backend=backend)
                self.assertEqual(len(node.select), 1, msg=f"{backend}: {src!r}")
                self.assertIsNotNone(getattr(node, attr), msg=f"{backend}: {src!r}")
            # bare clause keyword (no body) → stays a column;
            # `window from events` is `window` the Field then a FROM
            # clause, not a malformed WINDOW clause.
            for src in (
                "select a, where",
                "select a, having",
                "select a, window x",
                "select 1, window from events",
            ):
                node = parse_select(src, backend=backend)
                self.assertEqual(len(node.select), 2, msg=f"{backend}: {src!r}")

    def test_limit_percent_marker_with_compound_body(self):
        # `%` is overloaded: modulo operator and the `LIMIT … PERCENT`
        # marker. When the LIMIT body is a compound expression the
        # marker `%` lands after a lower-precedence operator; the Rust
        # parser used to bind it as modulo and choke on `WITH TIES`.
        # The cpp-json oracle is the source of truth; assert all three
        # backends agree on the parsed AST.
        cases = (
            "SELECT 1 LIMIT 1+1 % WITH TIES",
            "SELECT a, b LIMIT c AND d % WITH TIES",
            "SELECT 1 LIMIT 1+1 % 2 WITH TIES",
            "SELECT 1 LIMIT a%b % WITH TIES",
            "SELECT 1 LIMIT 5 % 2 + 3",
            "SELECT 1 LIMIT 1+1 % OFFSET 3",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_assignment_lhs_is_any_expression(self):
        # `exprStmt: expression (COLONEQUALS expression)?` puts no
        # target restriction on the `:=` left-hand side — cpp builds a
        # `VariableAssignment` for any `<expr> := <expr>`. The Rust
        # parser rejected non-place LHSs ("cannot assign to this
        # expression"); a rejected `:=` body inside a `for` then made
        # the whole `for` fail and mis-report "unexpected Let".
        cases = (
            "1 := 1",
            "[] := 1",
            "{} := 1",
            "'s' := 1",
            "return 1 := 1",
            "for (let m in 488614) 1 := 1",
        )
        for src in cases:
            oracle = clear_locations(parse_program(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_program(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_call_as_assignment_target(self):
        # A statement's leading expression folds its own postfix `(…)`
        # call even when `:=` follows — `f() := 1` is
        # `Call(f) := 1`, `if(x) := y` is `Call(if,[x]) := y`. The
        # Rust parser ran the leading expr through the
        # `stop_postfix_call_before_colon_equals` guard (which is meant
        # only for RHS parsing) and split it into two statements.
        cases = (
            "f() := 1",
            "f(x) := 1",
            "f()(g) := h",
            "if(x) := y",
            # the guard's real RHS scenario must still hold
            "(a) := (b) (c) := (d)",
        )
        for src in cases:
            oracle = clear_locations(parse_program(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_program(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_assignment_statement_consumes_trailing_semicolon(self):
        # `exprStmt: expression (COLONEQUALS expression)? SEMICOLON?` —
        # the `:=` form is an exprStmt and consumes its optional
        # trailing `;`. Without that, `if (c) a := b ; else d` strands
        # the `;` and the `else` is parsed as a bare Field instead of
        # binding to the `if`. (`varDecl`'s `LET …` form has no
        # `SEMICOLON?` and must not consume it.)
        cases = (
            "if (c) a := b ; else d",
            "if (c) (a) := b ; else d",
            "if (c) a := b ;; else d",
        )
        for src in cases:
            oracle = clear_locations(parse_program(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_program(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_decoration_after_pivot(self):
        # `tableExpr PIVOT (…)` is itself a `tableExpr`, so the result
        # can still take a `TableExprAlias` alias and a `JoinExprTable`
        # `FINAL? sampleClause?`, and a further PIVOT / JOIN can follow.
        # The Rust parser parsed PIVOT as a one-shot at the join level
        # and stopped, rejecting the trailing tokens.
        cases = (
            "SELECT 1 FROM (t PIVOT (a FOR b IN (c)) FINAL)",
            "SELECT 1 FROM (t PIVOT (a FOR b IN (c)) SAMPLE 1)",
            "SELECT 1 FROM (t UNPIVOT (a FOR b IN (c)) FINAL)",
            "SELECT 1 FROM t PIVOT (a FOR b IN (c)) FINAL",
            "SELECT 1 FROM t PIVOT (a FOR b IN (c)) AS x",
            "SELECT 1 FROM t PIVOT (a FOR b IN (c)) x",
            "SELECT 1 FROM t PIVOT (a FOR b IN (c)) AS x PIVOT (d FOR e IN (f))",
            "SELECT 1 FROM t PIVOT (a FOR b IN (c)) JOIN u ON x",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_clause_keyword_as_last_group_by_key(self):
        # `GROUP BY tool, window HAVING …` — `window` is the WINDOW
        # clause keyword and also a valid Field. As the last GROUP BY
        # key (after a comma, immediately followed by another clause)
        # it must stay a group_by key, not flip the parser into WINDOW
        # clause parsing. The eight-token shape is taken straight from
        # a production query rendered 232x in 7 days.
        for backend in _BACKENDS:
            for kw in ("window", "having", "qualify"):
                node = parse_select(
                    f"SELECT a FROM events GROUP BY tool, {kw} HAVING call_count >= 5",
                    backend=backend,
                )
                self.assertIsInstance(node, ast.SelectQuery, msg=f"{backend}: {kw}")
                self.assertEqual(len(node.group_by or []), 2, msg=f"{backend}: {kw}")
                self.assertIsNotNone(node.having, msg=f"{backend}: {kw}")
