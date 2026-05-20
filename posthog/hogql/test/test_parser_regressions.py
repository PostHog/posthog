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
from posthog.hogql.errors import (
    ExposedHogQLError,
    SyntaxError as HogQLSyntaxError,
)
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

    def test_trailing_limit_offset_compound_body(self):
        # The `LIMIT`/`OFFSET` that may follow a `LIMIT BY` clause takes
        # a full `columnExpr` body. The Rust parser parsed it bounded
        # at BP_MULT+1, stranding any lower-precedence tail
        # (`limit (x) ?? y`, `offset a ?? b`).
        cases = (
            "select x limit a by c limit d ?? e",
            "select x limit a by c offset d ?? e",
            "select x limit a by c limit 1 + 1",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_zero_arg_lambda_as_clause_body(self):
        # `() -> body` is a zero-arg lambda. After a trailing comma a
        # clause keyword followed by `( )` is normally an empty call on
        # the keyword-as-Field (`select 1, where ()`), but `( ) ->` is
        # a lambda parameter list — a valid clause body — so the
        # keyword stays a clause introducer.
        cases = (
            "select 1, limit () -> 2",
            "select 1, where () -> 2",
            "select 1, offset () -> 3",
            "select 1, limit ()",  # bare () — keyword is a column
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_set_level_offset_compound_body(self):
        # `offsetOnlyClause: OFFSET columnExpr` at the selectSetStmt
        # level takes a full `columnExpr`. The Rust parser parsed it
        # bounded at BP_MULT+1, stranding a lower-precedence tail
        # (`offset (x) or y`, `offset (x) ignore nulls`).
        cases = (
            "select 1 offset a or b",
            "select 1 offset a ignore nulls",
            "(select 1) offset a ?? b",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_pivot_tuple_or_single_parenthesised_operand(self):
        # `columnExprTupleOrSingle: LPAREN columnExprList RPAREN |
        # columnExpr` — a parenthesised PIVOT/UNPIVOT operand is always
        # a `Tuple`, even for one element (`(x)` → Tuple([x])). The
        # Rust parser stripped the parens for the single-element case.
        cases = (
            "select 1 from a unpivot ((x) for (c) in (d))",
            "select 1 from a pivot (s for (c) in (1))",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_pivot_binds_to_last_joined_table(self):
        # `joinExpr PIVOT` is left-recursive on the immediately
        # preceding joinExpr: `a JOIN b PIVOT (…)` pivots `b` alone,
        # not the whole `a JOIN b` chain. A PIVOT after a join
        # constraint (`a JOIN b ON x PIVOT (…)`) or explicit parens
        # (`(a JOIN b) PIVOT (…)`) does apply to the whole chain. The
        # Rust parser wrapped the entire chain unconditionally.
        cases = (
            "select 1 from a join b pivot (x for y in (z))",
            "select 1 from a, b pivot (x for y in (z))",
            "select 1 from a join b on x pivot (s for t in (u))",
            "select 1 from (a join b) pivot (x for y in (z))",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_columns_macro_asterisk_form_as_list_element(self):
        # `COLUMNS (…)` resolves `columnExprList` before the dedicated
        # `* EXCLUDE` / `id.* …` alternatives. An asterisk-form
        # followed by a postfix `(…)` call (`columns(q.*())`,
        # `columns(* exclude(a) ())`) is a `ColumnsList` whose element
        # is an `ExprCall` over the asterisk-form — not a plain
        # `Call(columns, …)`. The Rust parser committed to the
        # dedicated form and then fell back to a function call when the
        # trailing `(…)` would not parse.
        cases = (
            "columns(q.*())",
            "columns(* exclude(a) ())",
            # guard: the plain forms must keep their shape
            "columns(*)",
            "columns(a, b)",
            "columns(q.*)",
            "columns(* exclude(a))",
            "columns('re')",
        )
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_columns_replace_item_name_is_the_as_keyword(self):
        # `columnsReplace: columnExpr AS identifier` — the replacement
        # name can itself be the keyword `as` (`* replace(a AS as)`).
        # The Rust parser located the separator `AS` as the last `Kw::As`
        # token of the item, which is the *name* in that case; it must
        # use the second-to-last token instead.
        cases = (
            "(* replace(a as as))",
            "columns(* replace(a as as))",
            "(* replace(a as b as as))",
            "columns(* replace(x as y, z as as))",
            # guard: ordinary names still work
            "(* replace(a as b))",
        )
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_clause_keyword_then_postfix_op_is_a_column(self):
        # A clause keyword after the trailing comma followed by a
        # postfix operator (`?.`, `::`) is a column — `qualify?.q`,
        # `prewhere::q` — because a clause body cannot *start* with an
        # operator token. `peek_can_start_clause_body` wrongly accepted
        # pure infix/postfix tokens, so the Rust parser treated the
        # keyword as a clause and rejected the stranded operator.
        for backend in _BACKENDS:
            for src in (
                "select q, qualify ?. q",
                "select q, prewhere ?. q",
                "select q, prewhere :: q",
                "select q, having ?. r",
            ):
                node = parse_select(src, backend=backend)
                self.assertEqual(len(node.select), 2, msg=f"{backend}: {src!r}")
            # guard: a real expression-starter still opens the clause
            node = parse_select("select q, having y", backend=backend)
            self.assertEqual(len(node.select), 1, msg=f"{backend}: having y")

    def test_from_after_comma_needs_a_table_reference(self):
        # FROM's clause body is a `joinExpr` (a table reference), not a
        # `columnExpr`. After a trailing comma `from` only opens the
        # FROM clause when a table-reference starter follows; otherwise
        # it stays a Field column (`select q, from` → two columns,
        # `select q, from + 1` → `q` and `from + 1`). The Rust parser
        # broke the column list on `from` unconditionally.
        for backend in _BACKENDS:
            for src in ("select q, from", "select q, from + 1", "select q, from()"):
                node = parse_select(src, backend=backend)
                self.assertEqual(len(node.select), 2, msg=f"{backend}: {src!r}")
                self.assertIsNone(node.select_from, msg=f"{backend}: {src!r}")
            # guard: a real table reference still opens the FROM clause
            node = parse_select("select q, from t", backend=backend)
            self.assertEqual(len(node.select), 1, msg=f"{backend}: from t")
            self.assertIsNotNone(node.select_from, msg=f"{backend}: from t")

    def test_clause_keyword_asterisk_then_postfix_is_a_clause(self):
        # `<clause-kw> * <postfix-op>` — `qualify * ?. q` — is the
        # clause whose body is the asterisk-spread `*` extended by the
        # postfix op, not `<clause-kw-field> * …` arithmetic: the `*`'s
        # multiplication RHS cannot begin with a postfix operator. The
        # Rust `asterisk_after_offset_continues_arith` probe answered
        # "continues arithmetic" for an operator token after `*`.
        for backend in _BACKENDS:
            for src in (
                "select q, qualify * ?. q",
                "select q, where * :: r",
                "select q, having * ?. r",
                "select q, offset * ?. r",
            ):
                node = parse_select(src, backend=backend)
                self.assertEqual(len(node.select), 1, msg=f"{backend}: {src!r}")
            # guard: `where * r` is `where` the column times `r`
            node = parse_select("select q, where * r", backend=backend)
            self.assertEqual(len(node.select), 2, msg=f"{backend}: where * r")

    def test_pivot_tuple_or_single_operand_with_postfix(self):
        # `columnExprTupleOrSingle: LPAREN columnExprList RPAREN |
        # columnExpr`. A parenthesised PIVOT/UNPIVOT operand is a
        # `Tuple` only when the matching `)` is followed by `FOR` /
        # `IN` (the operand boundary). When a postfix follows — `(n)()`
        # — it is the `columnExpr` alternative: a parenthesised
        # expression extended by the postfix call. The Rust parser
        # always took the Tuple branch and stranded the `()`.
        cases = (
            "select 1 from a unpivot (m for (n)() in (p))",
            "select 1 from a pivot (m for (n)() in (p))",
            # guard: a bare parenthesised operand stays a Tuple
            "select 1 from a unpivot (m for (n) in (p))",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_window_frame_between_falls_back_to_field(self):
        # `winFrameExtend: winFrameBound | BETWEEN winFrameBound AND
        # winFrameBound`. After ROWS / RANGE a `between` is ambiguous:
        # the `frameBetween` alt, or a `frameStart` bound whose
        # `columnExpr` is the `between` keyword used as a Field
        # (`RANGE BETWEEN PRECEDING` → frame expr = Field(between)).
        # The Rust parser committed to the `frameBetween` alt on
        # seeing `between` and rejected the un-`AND`ed frame.
        cases = (
            "select 1 from a window w as (range between preceding)",
            # guard: a real BETWEEN frame still parses
            "select 1 from a window w as (range between 1 preceding and 2 following)",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_pivot_operand_containing_in(self):
        # A PIVOT/UNPIVOT `columnExprTupleOrSingle` operand is a full
        # `columnExpr` and may contain the `in` comparison operator
        # (`for n in p in (r)` → operand `n in p`, then the structural
        # `IN (r)`). The Rust parser bounded the operand above `IN`'s
        # binding power, dropping any operand-internal `in` (and the
        # `for`-operand's too).
        cases = (
            "select 1 from a unpivot (m for n in p in (r))",
            "select 1 from a pivot (m for n in p in (r))",
            "select 1 from a unpivot (m in n for p in (r))",
            # guard: the simple form still parses
            "select 1 from a pivot (m for n in (r))",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
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

    def test_integer_literal_above_i64_max(self):
        # An integer literal wider than i64 is kept lossless — never
        # narrowed to a float, all the way up through u64 and into
        # arbitrary-precision bigints. The value can't round-trip as a
        # native JSON number (orjson rejects >64-bit number tokens), so
        # the JSON backends carry the exact digits as a string in the
        # `value_type: "number"` envelope; all three backends must
        # agree on the exact int.
        cases = {
            "9223372036854775808": 9223372036854775808,  # i64::MAX + 1
            "18446744073709551615": 18446744073709551615,  # u64::MAX
            "18446744073709551616": 18446744073709551616,  # u64::MAX + 1
            "99999999999999999999999999": 99999999999999999999999999,
            "-9223372036854775809": -9223372036854775809,  # i64::MIN - 1
            "0x8000000000000000": 0x8000000000000000,
            "0xFFFFFFFFFFFFFFFFFF": 0xFFFFFFFFFFFFFFFFFF,
        }
        for src, expected in cases.items():
            for backend in _BACKENDS:
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.Constant, msg=f"{backend}: {src!r}")
                self.assertEqual(node.value, expected, msg=f"{backend}: {src!r}")
                self.assertIsInstance(node.value, int, msg=f"{backend}: {src!r}")

    def test_string_escape_nul_bel_vtab(self):
        # cpp's string.cpp drops `\0` (NUL ignored) and decodes
        # `\a`→0x07, `\v`→0x0B. The Rust decode_quoted_body emitted a
        # real NUL for `\0` and left `\a`/`\v` as literal backslash
        # sequences. `\0` also affects quoted identifiers.
        cases = (
            r"'a\0b'",
            r"'\a'",
            r"'\v'",
            r"`a\0b`",
            r'"a\0b"',
        )
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_reserved_keyword_alias_rejected(self):
        # cpp calls assertValidAlias at all four alias sites, rejecting
        # an unquoted `true`/`false`/`null`/`team_id`. The Rust parser
        # only checked the `AS`-infix path; the alias-before
        # (`x : 1`), implicit-alias and table-alias sites were
        # unchecked. Quoted forms opt out and must still parse.
        for backend in _BACKENDS:
            for src in (
                "select 1 as team_id from t",  # AS-infix (already checked)
                "select 1 team_id from t",  # implicit alias
                "select team_id : 1 from t",  # alias-before
                "select * from t as team_id",  # table alias (AS)
                "select * from t team_id",  # table alias (bare)
            ):
                with self.assertRaises(ExposedHogQLError, msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            # Quoted aliases opt out of the reserved-keyword check.
            for src in (
                'select 1 as "team_id" from t',
                'select 1 "team_id" from t',
                'select * from t as "team_id"',
            ):
                parse_select(src, backend=backend)

    def test_settings_and_top_clause_error_class(self):
        # SETTINGS and TOP are accepted by the grammar but rejected by
        # the visitor as unsupported — cpp throws NotImplementedError,
        # surfaced by the JSON backend as a bare ExposedHogQLError. The
        # Rust parser never consumed either clause and fell out with a
        # generic SyntaxError; the error *class* must match cpp's.
        for src in ("SELECT 1 SETTINGS x = 1", "SELECT TOP 5 x FROM t"):
            with self.assertRaises(ExposedHogQLError) as cpp_cm:
                parse_select(src, backend="cpp-json")
            with self.assertRaises(ExposedHogQLError) as rust_cm:
                parse_select(src, backend="rust-json")
            self.assertIs(type(rust_cm.exception), type(cpp_cm.exception), msg=src)
            self.assertNotIsInstance(rust_cm.exception, HogQLSyntaxError, msg=src)

    def test_window_frame_non_int_bound_keeps_constant(self):
        # cpp's VISIT(WinFrameBound) unwraps a frame-bound Constant to a
        # bare number only when the value is an integer; a float or
        # string Constant keeps its full object form. The Rust parser
        # unwrapped any Constant. (The pure-Python backend diverges from
        # cpp on a non-int bound too — a separate cpp-vs-python issue —
        # so this pins rust against cpp.)
        cases = (
            "SELECT count() OVER (ROWS 1.5 PRECEDING) FROM t",
            "SELECT count() OVER (ROWS '5' PRECEDING) FROM t",
            "SELECT count() OVER (ROWS 2 PRECEDING) FROM t",  # guard: int still bare
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            got = clear_locations(parse_select(src, backend="rust-json"))
            self.assertEqual(got, oracle, msg=f"rust-json: {src!r}")

    def test_boolean_keyword_as_call_name(self):
        # `true`/`false` are ordinary identifiers in the grammar, not
        # lexer tokens — they become Bool Constants only as a bare
        # columnIdentifier. As a function-call name cpp builds a
        # `Call(name=...)`. The Rust lexer makes them keywords, so the
        # parser folded `true(1)` into `ExprCall(Constant(true), …)`.
        # `null` differs — `NULL` is a real keyword, so `null(1)` stays
        # an `ExprCall` on the Null constant in both parsers.
        for src in ("true(1)", "false(1)", "null(1)"):
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")
        # guard: bare true/false/null are still Constants
        for src, val in (("true", True), ("false", False), ("null", None)):
            node = parse_expr(src, backend="rust-json")
            self.assertIsInstance(node, ast.Constant, msg=src)
            self.assertEqual(node.value, val, msg=src)

    def test_hex_integer_literal_baseline(self):
        # Pins existing hex integer behaviour so the hex-float lexer
        # changes can't accidentally regress plain `0x…` parsing. `e`
        # and `E` are hex digits in this context (not exponent markers
        # — that only kicks in when a `[+-]?<dec>+` exponent suffix
        # follows them).
        cases = {
            "0x0": 0,
            "0x1": 1,
            "0xff": 255,
            "0xFF": 255,
            "0XFF": 255,
            "0xe": 14,  # `e` alone is a hex digit, not an exp marker
            "0xE": 14,
            "0x1e": 30,
            "0x1E": 30,
            "0x1e5": 485,  # three hex digits, NOT a float
            "0xabc": 2748,
            "0xABC": 2748,
            "0xfe": 254,
            "0xae": 174,
            # signed
            "-0x1": -1,
            "+0xff": 255,
            "-0xff": -255,
            # lossless past i64 (preserved by the recent lossless-int fix)
            "0xFFFFFFFFFFFFFFFF": 18446744073709551615,
            "0xFFFFFFFFFFFFFFFFFF": 4722366482869645213695,
        }
        for src, expected in cases.items():
            for backend in _BACKENDS:
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.Constant, msg=f"{backend}: {src!r}")
                self.assertEqual(node.value, expected, msg=f"{backend}: {src!r}")
                self.assertIsInstance(node.value, int, msg=f"{backend}: {src!r}")

    def test_hex_float_literal_c99(self):
        # `FLOATING_LITERAL` for hex-floats: strict C99 `HEX P [+-]? DEC+`
        # and `HEX DOT HEX* P [+-]? DEC+`. `p`/`P` is the *only* hex-float
        # exponent marker — `e`/`E` is always a hex digit in this
        # context. cpp used to route hex through `stoll` and return only
        # the leading hex integer; rust and python rejected entirely.
        cases = {
            # P-marker, no fraction
            "0x1p4": float.fromhex("0x1p4"),  # 16.0
            "0x1p+4": float.fromhex("0x1p+4"),  # 16.0
            "0x1p-4": float.fromhex("0x1p-4"),  # 0.0625
            "0xAp1": float.fromhex("0xap1"),  # 20.0
            "0xap1": float.fromhex("0xap1"),  # 20.0
            "0x0p0": float.fromhex("0x0p0"),  # 0.0
            "0xffp10": float.fromhex("0xffp10"),  # 261120.0
            # P-marker, with fraction
            "0x1.8p3": float.fromhex("0x1.8p3"),  # 12.0
            "0x1.0p3": float.fromhex("0x1.0p3"),  # 8.0
            "0xab.cdp4": float.fromhex("0xab.cdp4"),
            "0xff.fp-4": float.fromhex("0xff.fp-4"),
            # `e`/`E` is a hex digit even when adjacent to `p`. `0xep1`
            # is hex mantissa `0xe` (14) + `p1` exponent → 28.0.
            "0xep1": float.fromhex("0xep1"),  # 28.0
            "0xEp1": float.fromhex("0xep1"),
            "0xeep1": float.fromhex("0xeep1"),  # 476.0
            # Signed
            "-0x1p4": -float.fromhex("0x1p4"),  # -16.0
            "+0x1p4": float.fromhex("0x1p4"),  # 16.0
        }
        for src, expected in cases.items():
            for backend in _BACKENDS:
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.Constant, msg=f"{backend}: {src!r}")
                self.assertIsInstance(node.value, float, msg=f"{backend}: {src!r}")
                self.assertEqual(node.value, expected, msg=f"{backend}: {src!r}")

    def test_hex_e_is_hex_digit_not_exponent_marker(self):
        # `e`/`E` after a hex digit run does NOT act as a hex-float
        # exponent marker. `0x1e+4` is the hex integer `0x1e` (=30)
        # followed by an arithmetic `+4`, NOT the hex-float
        # `0x1 × 2^4` = 16. Only `p`/`P` marks a hex-float exponent;
        # this matches strict C99 and ClickHouse runtime semantics.
        for src, op, lhs, rhs in (
            ("0x1e+4", "+", 30, 4),
            ("0x1e-4", "-", 30, 4),
            ("0x1E+4", "+", 30, 4),
            ("0xe+5", "+", 14, 5),
            ("0xff-1", "-", 255, 1),
        ):
            for backend in _BACKENDS:
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.ArithmeticOperation, msg=f"{backend}: {src!r}")
                self.assertEqual(node.op, op, msg=f"{backend}: {src!r}")
                self.assertEqual(node.left.value, lhs, msg=f"{backend}: {src!r}")
                self.assertEqual(node.right.value, rhs, msg=f"{backend}: {src!r}")

    def test_hex_float_in_expression_context(self):
        # A hex-float literal participates in surrounding expressions
        # like any other Constant. Pins that the lexer recognises the
        # whole hex-float as one token.
        for src, op, lhs, rhs in (
            ("0x1p4 + 1", "+", float.fromhex("0x1p4"), 1),
            ("1 + 0x1p4", "+", 1, float.fromhex("0x1p4")),
            ("0x1p4 * 2", "*", float.fromhex("0x1p4"), 2),
        ):
            for backend in _BACKENDS:
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.ArithmeticOperation, msg=f"{backend}: {src!r}")
                self.assertEqual(node.op, op, msg=f"{backend}: {src!r}")
                self.assertIsInstance(node.left, ast.Constant, msg=f"{backend}: {src!r}")
                self.assertIsInstance(node.right, ast.Constant, msg=f"{backend}: {src!r}")
                self.assertEqual(node.left.value, lhs, msg=f"{backend}: {src!r}")
                self.assertEqual(node.right.value, rhs, msg=f"{backend}: {src!r}")

    def test_hex_float_no_integer_part_rejected(self):
        # `0x.8p3` lacks a HEX_DIGIT+ before the dot — invalid per
        # both the FLOATING_LITERAL and HEXADECIMAL_LITERAL grammar.
        # All three backends must reject.
        for backend in _BACKENDS:
            with self.assertRaises(ExposedHogQLError, msg=f"{backend}: '0x.8p3'"):
                parse_expr("0x.8p3", backend=backend)

    def test_cast_type_arg_with_parenthesized_expr(self):
        # `CAST(x AS name(...))` parses the type as a columnTypeExpr; the
        # `ColumnTypeExprParam` form (`identifier LPAREN columnExprList?
        # RPAREN`) admits arbitrary column exprs in its argument list,
        # including ones with their own `(…)` groups. cpp builds a
        # TypeCast and captures the raw type text; the Rust parser fell
        # out of the CAST type-expr path when the type arg contained a
        # parenthesised expression and re-parsed the whole thing as a
        # plain `cast(...)` function call.
        cases = (
            "cast(x as a((b)))",
            "cast(x as a(case when (c) then d end))",
            "cast(x as a(if((c), d, e)))",
        )
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_subquery_arg_call_then_second_call(self):
        # `f(select 1)` is a `ColumnExprCallSelect` (`columnExpr LPAREN
        # selectSetStmt RPAREN`); a trailing `()` is a separate
        # `ColumnExprCall` postfix that nests on top — cpp builds
        # `ExprCall(Call(f, [SelectQuery]), [])`. The Rust parser folded
        # both groups into a single parametric `Call(params=[…], args=[…])`,
        # which is only valid when the first group is a columnExprList
        # (a SelectQuery is not).
        cases = (
            "f(select 1)()",
            "a(select 1)(2)",
            "f(select 1)(x)(y)",
        )
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_between_not_lambda_lower_bound(self):
        # `a BETWEEN <low> AND <high>` requires the low-bound parse to
        # leave its own AND available for the BETWEEN. With a bare
        # lambda low bound the Rust parser gets this right, but with
        # `NOT` wrapping the lambda the AND-reservation context is lost
        # across the `NOT` prefix into the lambda body, so the lambda
        # over-consumes `… and c` and the BETWEEN has no AND left.
        cases = (
            "a between not lambda x: b and c",
            "a between not x -> y and z",
        )
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_bare_asterisk_clause_body_after_comma(self):
        # A clause keyword after a trailing comma with a bare `*` body
        # starts its clause; the following LIMIT / WITH TOTALS / GROUP
        # BY is a normal subsequent clause. Same family as the existing
        # `test_clause_keyword_after_comma_in_select_columns`, but
        # uncovered for the bare-`*` body. The Rust parser used to keep
        # `where *` as a select column and choke on the trailing clause.
        cases = (
            "select a, where * limit 1",
            "select a, where * with totals",
            "select a, prewhere * with totals",
            "select a, where * group by x",
            "select a, where * order by x",
            "select a, having * limit 1",
            "select a, qualify * limit 1",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_placeholder_statement_then_postfix_call_or_property(self):
        # `{expr}` at statement start is a placeholder expression; a
        # trailing `(…)` call or `.x` property access is a postfix on
        # it. The Rust parser committed `{1}` to a `block` statement
        # and failed on the dangling postfix token. It already
        # reconsiders for `[` and `+`, so the disambiguation set is
        # incomplete (`(` and `.` were missing).
        cases = (
            "{1}()",
            "{1}.x",
            "{a}()",
            "{ {1}() }",
        )
        for src in cases:
            oracle = clear_locations(parse_program(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_program(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_window_frame_bound_low_precedence_value(self):
        # A window frame bound's value is a full `columnExpr`, so it
        # admits comparison / AND / OR operators. The Rust parser
        # parsed it above comparison binding power and rejected
        # `ROWS a = b PRECEDING`.
        cases = (
            "SELECT count() OVER (ROWS a = b PRECEDING) FROM t",
            "SELECT count() OVER (ROWS a AND b FOLLOWING) FROM t",
            # guard: a BETWEEN frame still splits on its own AND
            "SELECT count() OVER (ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_join_op_modifier_arity_validation(self):
        # Per `HogQLParser.g4:127-134`, each joinOp alt restricts
        # ALL/ANY/ASOF to at most one occurrence; ANTI/SEMI combine
        # only with ASOF in inner-style and only as `ASOF (ANTI|SEMI)`
        # (the reverse order is invalid).
        from posthog.hogql.errors import BaseHogQLError

        invalid = (
            "SELECT 1 FROM a ANTI ASOF JOIN b ON 1",
            "SELECT 1 FROM a SEMI ASOF JOIN b ON 1",
            "SELECT 1 FROM a SEMI ANTI JOIN b ON 1",
            "SELECT 1 FROM a ALL ANTI JOIN b ON 1",
            "SELECT 1 FROM a ALL ASOF JOIN b ON 1",
            "SELECT 1 FROM a ALL ANY JOIN b ON 1",
        )
        for src in invalid:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
        # Valid combinations still parse.
        for src in (
            "SELECT 1 FROM a ASOF JOIN b ON 1",
            "SELECT 1 FROM a ASOF ANTI JOIN b ON 1",
            "SELECT 1 FROM a ASOF SEMI JOIN b ON 1",
            "SELECT 1 FROM a ASOF LEFT JOIN b ON 1",
            "SELECT 1 FROM a SEMI LEFT JOIN b ON 1",
        ):
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_group_by_all_falls_back_to_columns_on_postfix(self):
        # `groupByClause: GROUP BY (ALL | (CUBE|ROLLUP) LPAREN … |
        # GROUPING SETS LPAREN … | columnExprList)`. `ALL` is also a
        # keyword-as-identifier per the grammar's `keyword` rule, so
        # any postfix token after `ALL` makes cpp's ALL(*) fall back
        # to `columnExprList` with `Field('ALL')` as the first item.
        # Rust eagerly committed to the all-mode marker.
        for src in (
            "SELECT a FROM t GROUP BY ALL, b",
            "SELECT a FROM t GROUP BY ALL.x",
            "SELECT a FROM t GROUP BY ALL + 1",
            "SELECT a FROM t GROUP BY ALL[1]",
            "SELECT a FROM t GROUP BY ALL()",
        ):
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")
        # Guard: bare `ALL` (followed by a clause terminator) still
        # hits the all-mode marker.
        oracle = clear_locations(parse_select("SELECT a FROM t GROUP BY ALL", backend="cpp-json"))
        for backend in ("rust-json", "python"):
            got = clear_locations(parse_select("SELECT a FROM t GROUP BY ALL", backend=backend))
            self.assertEqual(got, oracle, msg=backend)

    def test_with_rollup_cube_totals_chain_grammar(self):
        # cpp: `groupByClause … (WITH (CUBE|ROLLUP))? (WITH TOTALS)?`.
        # At most one CUBE/ROLLUP, then optionally TOTALS, in order.
        # Rust accepted any number/order via an unbounded loop.
        from posthog.hogql.errors import BaseHogQLError

        invalid = (
            "SELECT a FROM t GROUP BY a WITH ROLLUP WITH CUBE",
            "SELECT a FROM t GROUP BY a WITH ROLLUP WITH ROLLUP",
            "SELECT a FROM t GROUP BY a WITH TOTALS WITH ROLLUP",
            "SELECT a FROM t GROUP BY a WITH TOTALS WITH TOTALS",
        )
        for src in invalid:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
        # Valid combinations still parse.
        for src in (
            "SELECT a FROM t GROUP BY a WITH ROLLUP",
            "SELECT a FROM t GROUP BY a WITH CUBE",
            "SELECT a FROM t GROUP BY a WITH TOTALS",
            "SELECT a FROM t GROUP BY a WITH ROLLUP WITH TOTALS",
            "SELECT a FROM t GROUP BY a WITH CUBE WITH TOTALS",
        ):
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_pivot_in_list_must_be_non_empty(self):
        # `pivotColumn: columnExprTupleOrSingle IN LPAREN columnExprList
        # RPAREN` — the columnExprList is non-empty. cpp rejects
        # empty `IN ()`; rust was silently producing an empty list.
        from posthog.hogql.errors import BaseHogQLError

        with self.assertRaises((BaseHogQLError, SyntaxError)):
            parse_select(
                "SELECT 1 FROM t PIVOT (sum(x) FOR y IN ())", backend="rust-json"
            )
        with self.assertRaises((BaseHogQLError, SyntaxError)):
            parse_select(
                "SELECT 1 FROM t PIVOT (sum(x) FOR y IN ())", backend="cpp-json"
            )
        # Guard: populated list still parses.
        src = "SELECT 1 FROM t PIVOT (sum(x) FOR y IN (1, 2))"
        oracle = clear_locations(parse_select(src, backend="cpp-json"))
        for backend in ("rust-json", "python"):
            got = clear_locations(parse_select(src, backend=backend))
            self.assertEqual(got, oracle, msg=backend)

    def test_trim_substring_must_be_string_literal(self):
        # `TRIM (LEADING|TRAILING|BOTH string FROM columnExpr)` where
        # `string: STRING_LITERAL | templateString`. Rust accepted any
        # columnExpr in the substring slot; cpp rejects everything
        # except a string literal or template string.
        from posthog.hogql.errors import BaseHogQLError

        invalid = (
            "TRIM(BOTH x FROM y)",
            "TRIM(BOTH 1 FROM y)",
            "TRIM(BOTH f() FROM y)",
            "TRIM(LEADING (a) FROM y)",
        )
        for src in invalid:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
        # Guards: string literal + template string still parse.
        for src in ("TRIM(BOTH 'x' FROM y)", "TRIM(LEADING f'x' FROM y)"):
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_cte_list_paren_after_non_paren_cte(self):
        # A column-form CTE followed by a CTE whose head token is `(`
        # (paren-wrapped subquery or paren'd expression) must continue
        # the CTE list, not terminate it. The Rust parser used to break
        # the loop on the leading `(` because of the trailing-comma
        # tolerance for `, SELECT`.
        for src in (
            "WITH 1 AS x, (SELECT 1) AS y SELECT x, y",
            "WITH (SELECT 1) AS x, (SELECT 2) AS y SELECT x, y",
            "WITH 1 AS x, (a + b) AS y SELECT y",
            "WITH 1 AS x, (1) AS y SELECT y",
            "WITH 1 AS a, (x -> x + 1) AS f SELECT f(a)",
            "WITH count() AS c, (x -> x + 1) AS f SELECT f(c)",
        ):
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_group_by_cube_rollup_continues_list(self):
        # cpp's ALL(*) treats `CUBE(...)` / `ROLLUP(...)` as ordinary
        # function calls when followed by `, <more>` keys; the
        # specialised `(CUBE|ROLLUP) LPAREN ... RPAREN` mode commits
        # only when no list continuation follows. Rust's eager commit
        # to the specialised branch swallowed the parens and left the
        # trailing `,` stranded.
        for src in (
            "SELECT * FROM t GROUP BY CUBE(a), ROLLUP(b)",
            "SELECT * FROM t GROUP BY CUBE(a), b",
            "SELECT * FROM t GROUP BY ROLLUP(a), b",
            "SELECT * FROM t GROUP BY a, CUBE(b)",
        ):
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")
        # Bare `GROUP BY CUBE(...)` (no trailing keys) still uses the mode.
        for src in (
            "SELECT * FROM t GROUP BY CUBE(a)",
            "SELECT * FROM t GROUP BY ROLLUP(a)",
        ):
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_trailing_comma_after_joined_table_chain(self):
        # cpp tolerates a stray trailing comma after a constrained JOIN
        # chain (`FROM a JOIN b ON 1,`) — the comma falls off the end
        # of the joinExpr without a following table atom. Rust's join
        # loop treated the comma unconditionally as a cross-join start
        # and demanded a following table atom.
        for src in (
            "SELECT * FROM a JOIN b ON 1,",
            "SELECT * FROM a JOIN b USING (x),",
            "SELECT * FROM a JOIN b ON 1 JOIN c ON 1,",
        ):
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_unterminated_block_comment_lexes_as_div_asterisk(self):
        # cpp's ANTLR lexer only matches the `/* ... */` comment rule
        # when a closing `*/` is found. An unterminated `/*` falls back
        # to `/` and `*` tokens, which the parser then evaluates per
        # the normal expression grammar. Rust used to commit eagerly
        # to the comment-skip path and silently advance to EOF, so
        # `1 /* unclosed` was happily returning `Constant(1)` and
        # dropping the trailing garbage.
        for src in ("1 /*", "1 /* "):
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

        # Unterminated `/*` followed by ident content lexes as
        # `1 / * ident`, which fails the expression parse with a
        # trailing-tokens / extraneous-input error in all three
        # backends (rather than silently consuming the rest as a
        # comment).
        from posthog.hogql.errors import BaseHogQLError

        for src in ("1 /* unclosed", "a /* unclosed"):
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)

        # Closed `/* ... */` is still trivia in all three backends.
        oracle = clear_locations(parse_expr("1 /* ok */ + 2", backend="cpp-json"))
        for backend in ("rust-json", "python"):
            got = clear_locations(parse_expr("1 /* ok */ + 2", backend=backend))
            self.assertEqual(got, oracle, msg=backend)

    def test_interpolate_no_trailing_comma(self):
        # `INTERPOLATE LPAREN interpolateExpr (COMMA interpolateExpr)*
        # RPAREN` — no trailing comma. cpp rejects; rust was accepting.
        from posthog.hogql.errors import BaseHogQLError

        for backend in ("cpp-json", "rust-json", "python"):
            with self.assertRaises((BaseHogQLError, SyntaxError), msg=backend):
                parse_select(
                    "SELECT 1 FROM t ORDER BY x WITH FILL INTERPOLATE (y,)",
                    backend=backend,
                )

    def test_boolean_dot_chain_is_field_not_array_access(self):
        # `true.x` / `false.x` is a property chain — cpp treats `true` /
        # `false` as ordinary identifiers in `columnIdentifier` chain
        # position and builds `Field(['true', 'x'])`. Rust was committing
        # the bool as `Constant(true)` first, then wrapping in
        # `ArrayAccess` via the Pratt `.` postfix.
        cases = ("true.x", "false.x", "TRUE.x", "true.x.y", "false.foo.bar")
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")
        # Guards: bare `true` / `false` stay Bool constants; `true(1)` is
        # a function call (ident path).
        for src in ("true", "false", "true(1)"):
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_using_empty_parens_rejected(self):
        # `joinConstraintClause`: `USING LPAREN columnExprList RPAREN`
        # / `USING columnExprList` — both require a non-empty list. cpp
        # rejects `USING ()`; rust was producing an empty list.
        from posthog.hogql.errors import BaseHogQLError

        with self.assertRaises((BaseHogQLError, SyntaxError)):
            parse_select("SELECT * FROM a JOIN b USING ()", backend="rust-json")
        with self.assertRaises((BaseHogQLError, SyntaxError)):
            parse_select("SELECT * FROM a JOIN b USING ()", backend="cpp-json")
        # Populated USING still parses.
        src = "SELECT * FROM a JOIN b USING (x)"
        oracle = clear_locations(parse_select(src, backend="cpp-json"))
        for backend in ("rust-json", "python"):
            got = clear_locations(parse_select(src, backend=backend))
            self.assertEqual(got, oracle, msg=backend)

    def test_group_by_cube_rollup_empty_is_function_call(self):
        # Empty `CUBE()` / `ROLLUP()` — cpp parses these as function
        # calls (the GROUP BY position carries one Call element, no
        # group_by_mode); rust's dedicated CUBE / ROLLUP handler ate
        # the empty parens and emitted `group_by=[]` + the mode marker.
        for src in ("SELECT 1 GROUP BY CUBE()", "SELECT 1 GROUP BY ROLLUP()"):
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")
        # Populated CUBE / ROLLUP still uses the mode marker.
        src = "SELECT 1 GROUP BY CUBE(a, b)"
        oracle = clear_locations(parse_select(src, backend="cpp-json"))
        for backend in ("rust-json", "python"):
            got = clear_locations(parse_select(src, backend=backend))
            self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_quoted_identifier_backslash_escapes(self):
        # `QUOTED_IDENTIFIER` grammar (`HogQLLexer.common.g4:160-163`):
        #   QUOTE_DOUBLE (~([\\"]) | ESCAPE_CHAR_COMMON | BACKSLASH QUOTE_DOUBLE | QUOTE_DOUBLE QUOTE_DOUBLE)* QUOTE_DOUBLE
        # — so `\"` inside `"..."` is a valid escape. Rust's lex_quoted_ident
        # treated `\` as just another body byte, terminating the ident
        # at the next unescaped `"` and rejecting the trailing `"`.
        cases = (
            '"\\""',
            '"a\\"b"',
            '"\\\\"',
            '"a"',
        )
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_reserved_keywords_rejected_as_identifiers(self):
        # Grammar's `identifier` rule (`IDENTIFIER | QUOTED_IDENTIFIER |
        # interval | keyword`) excludes NULL_SQL / INF / NAN_SQL /
        # EXCEPT / INTERSECT and the Hog-statement keywords (FN / FUN /
        # LET / WHILE / THROW / TRY / CATCH / FINALLY) — `keyword` lists
        # them out. cpp therefore rejects these as Field-chain links,
        # aliases, table identifiers, CTE column names, etc. Rust's
        # dotted-chain / alias / table-ident / columnAliases handlers
        # were accepting any `Keyword(_)` token without gating, so all
        # of these slipped through as identifiers.
        from posthog.hogql.errors import BaseHogQLError

        expr_invalid = (
            # Postfix DOT
            "a.except", "a.intersect", "a.null", "a.inf", "a.nan",
            "a.fn", "a.fun", "a.let", "a.while",
            "a.throw", "a.try", "a.catch", "a.finally",
            "a.b.except",
            # Postfix `?.`
            "a?.except", "a?.null", "a?.inf",
        )
        for src in expr_invalid:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)

        select_invalid = (
            # Alias position
            "SELECT a AS except FROM t",
            "SELECT a AS intersect FROM t",
            "SELECT a AS inf FROM t",
            "SELECT a AS nan FROM t",
            "SELECT a AS fn FROM t",
            "SELECT a AS let FROM t",
            # Table identifier
            "SELECT * FROM except.x",
            "SELECT * FROM x.except",
            "SELECT * FROM null.x",
            "SELECT * FROM fn.x",
            # WHERE / columnExpr position
            "SELECT 1 FROM t WHERE a.except",
            # CTE column-name list
            "WITH x (except, intersect) AS (SELECT 1, 2) SELECT * FROM x",
            "WITH x (a, null) AS (SELECT 1, 2) SELECT * FROM x",
            # columnAliases on subquery
            "SELECT a FROM (SELECT 1) AS x (except)",
        )
        for src in select_invalid:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
        # Guard: keywords that ARE valid identifiers per cpp's grammar
        # (interval units, plain keywords like CASE/DAY) still parse.
        for src in (
            "a.case", "a.day", "day.minute", "select.from",
            "SELECT a AS case FROM t",
            "SELECT a AS day FROM t",
        ):
            for backend in ("cpp-json", "rust-json", "python"):
                if "SELECT" in src:
                    self.assertIsNotNone(parse_select(src, backend=backend), msg=f"{backend}: {src!r}")
                else:
                    self.assertIsNotNone(parse_expr(src, backend=backend), msg=f"{backend}: {src!r}")

    def test_bare_asterisk_replace_only_inside_parens(self):
        # `ColumnExprAsterisk` (grammar line 289) admits ONLY an optional
        # trailing EXCLUDE on a bare `*`. `REPLACE` after `*` is valid
        # exclusively inside the paren-wrapped forms `(* REPLACE (…))`,
        # `(* EXCLUDE (…) REPLACE (…))`, and the `COLUMNS(* … REPLACE …)`
        # family. cpp rejects bare-`*` REPLACE at the top level; rust
        # was accepting it via the universal columns-decorator parse.
        from posthog.hogql.errors import BaseHogQLError

        invalid_select = ("SELECT * REPLACE (b AS a) FROM t",)
        for src in invalid_select:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
        with self.assertRaises((BaseHogQLError, SyntaxError)):
            parse_expr("* REPLACE (a AS b)", backend="rust-json")
        with self.assertRaises((BaseHogQLError, SyntaxError)):
            parse_expr("* REPLACE (a AS b)", backend="cpp-json")
        # Paren-wrapped form (and `EXCLUDE` decoration alone) still parse.
        for src in (
            "(* REPLACE (1 AS event))",
            "(* EXCLUDE (a) REPLACE (b AS c))",
            "* EXCLUDE (a)",
        ):
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_filter_clause_invalid_before_within_group(self):
        # `ColumnExprFunctionWithinGroup` (grammar line 234) is
        # `identifier LPAREN columnExprList? RPAREN withinGroupClause`
        # — no FILTER slot. cpp rejects
        # `f(args) FILTER (WHERE ...) WITHIN GROUP (...)`; rust was
        # silently dropping the FILTER expression.
        from posthog.hogql.errors import BaseHogQLError

        for src in (
            "median(x) FILTER (WHERE z) WITHIN GROUP (ORDER BY y)",
            "quantile(x) FILTER (WHERE z > 0) WITHIN GROUP (ORDER BY y)",
        ):
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
        # WITHIN GROUP alone still parses.
        oracle = clear_locations(parse_expr("median(x) WITHIN GROUP (ORDER BY y)", backend="cpp-json"))
        for backend in ("rust-json", "python"):
            got = clear_locations(parse_expr("median(x) WITHIN GROUP (ORDER BY y)", backend=backend))
            self.assertEqual(got, oracle, msg=backend)

    def test_window_function_args_no_distinct_no_inline_order_by(self):
        # `ColumnExprWinFunction` (grammar line 235) takes a plain
        # `columnExprList` — no DISTINCT, no in-args ORDER BY. cpp
        # rejects `foo(DISTINCT a) OVER ()` and `foo(a ORDER BY b)
        # OVER ()`; rust was accepting and silently dropping the
        # DISTINCT / ORDER BY.
        from posthog.hogql.errors import BaseHogQLError

        for src in (
            "foo(a ORDER BY b) OVER ()",
            "foo(DISTINCT a) OVER ()",
            "foo(DISTINCT a ORDER BY b) OVER ()",
        ):
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
        # Plain forms still parse.
        for src in ("foo(a) OVER ()", "foo(DISTINCT a)", "foo(a ORDER BY b)"):
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_unary_plus_only_on_numeric_literal(self):
        # `numberLiteral` grammar (line 380) makes `+` a sign prefix on
        # number / INF / NAN — not a general unary operator. cpp rejects
        # `+a`, `+f(x)`, `+(a)`, etc.; rust was bumping the `+` as a
        # no-op prefix and returning the RHS unchanged.
        from posthog.hogql.errors import BaseHogQLError

        invalid = ("+a", "+(a)", "+(+a)", "+f(x)")
        for src in invalid:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
        # Numeric / INF / NAN forms still parse identically.
        for src in ("+1", "+1.5", "+inf", "+nan"):
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                # NaN comparison is identity-only; pin parsing-success and
                # node-type rather than full equality.
                self.assertIsNotNone(got, msg=f"{backend}: {src!r}")
                if src not in ("+nan",):
                    self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_column_cte_requires_identifier_after_as(self):
        # `withExpr: columnExpr AS identifier` — the post-AS token must
        # be a valid identifier (incl. allowed keywords), not a number
        # / string / parenthesised group. cpp rejects; rust was using
        # the raw token text as the CTE name (e.g. `name='1'` for a
        # `WITH a AS 1` CTE).
        from posthog.hogql.errors import BaseHogQLError

        invalid = (
            "WITH a AS 1 SELECT a",
            "WITH 1 + 1 AS 1 SELECT 1",
            "WITH 1 + 1 AS 'foo' SELECT 'foo'",
        )
        for src in invalid:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
        # Identifier names continue to work.
        oracle = clear_locations(parse_select("WITH a AS b SELECT b", backend="cpp-json"))
        for backend in ("rust-json", "python"):
            got = clear_locations(parse_select("WITH a AS b SELECT b", backend=backend))
            self.assertEqual(got, oracle, msg=f"{backend}")

    def test_limit_offset_with_ties_must_precede_offset(self):
        # `limitAndOffsetClause` has two alternatives:
        #   compact: `LIMIT n PERCENT? (COMMA n)? (WITH TIES)?`
        #   verbose: `LIMIT n PERCENT? (WITH TIES)? OFFSET n`
        # `LIMIT n OFFSET m WITH TIES` doesn't match either — WITH TIES
        # must precede OFFSET in the verbose form. cpp rejects; rust
        # was accepting because `parse_limit_clauses` checked for WITH
        # TIES after both the Comma and Offset tails.
        from posthog.hogql.errors import BaseHogQLError

        with self.assertRaises((BaseHogQLError, SyntaxError)):
            parse_select("SELECT a FROM t LIMIT 1 OFFSET 2 WITH TIES", backend="rust-json")
        with self.assertRaises((BaseHogQLError, SyntaxError)):
            parse_select("SELECT a FROM t LIMIT 1 OFFSET 2 WITH TIES", backend="cpp-json")
        # Both valid forms still parse.
        for src in (
            "SELECT a FROM t LIMIT 1 WITH TIES OFFSET 2",
            "SELECT a FROM t LIMIT 1, 2 WITH TIES",
            "SELECT a FROM t LIMIT 1 WITH TIES",
        ):
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_pivot_in_separator_extends_via_postfix_call(self):
        # `pivotColumn: columnExprTupleOrSingle IN LPAREN columnExprList
        # RPAREN`. The LHS columnExprTupleOrSingle is a full columnExpr,
        # so cpp's ALL(*) greedy-extends it past any `IN (...)` group
        # whose closing `)` is followed by another `(` (a postfix call
        # on whatever LHS has built so far). Only the LAST `IN (...)`
        # — the one NOT followed by `(` — is the structural separator.
        # Rust's prior heuristic locked the FIRST depth-0 IN as the
        # structural one, mis-splitting `y IN (1) (2) IN (3)`.
        cases = (
            # Same shape, two pivotColumns split at the FIRST IN (b
            # after the first close means LHS-extension fails, so the
            # first IN is structural).
            "SELECT 1 FROM t PIVOT (s FOR a IN (1) b IN (2))",
            # ONE pivotColumn — LHS = `y IN (1)(2)` (CompareOperation
            # with postfix-call right), structural IN at the SECOND
            # depth-0 position.
            "SELECT 1 FROM t PIVOT (sum(x) FOR y IN (1) (2) IN (3))",
            # Baselines that must keep working.
            "SELECT 1 FROM t PIVOT (sum(x) FOR y IN (1, 2))",
            "SELECT 1 FROM t PIVOT (sum(x) FOR (y, z) IN ((a, b), (c, d)))",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_return_expr_prefix_shortened_when_assignment_follows(self):
        # `returnStmt: RETURN columnExpr? SEMICOLON?` — the columnExpr is
        # optional. When the full following expression would strand a
        # `:=`, cpp's ANTLR ALL(*) backtracks to the shortest expression
        # PREFIX that leaves the rest parseable as the next statement.
        # The shortenings cpp prefers:
        #
        #   `return * columns(…) := X` → expr = Field(['*']); the
        #     `columns(…) := X` is a VarAssignment with the columns
        #     call as its lvalue.
        #   `return columns(…) := X` → expr = Field(['columns']); the
        #     parens become a parenthesised columnExpr that takes `:=`.
        #
        # Rust's prior lookahead bailed all the way to a bare return,
        # producing a divergent AST shape.
        cases = (
            "fn f() { return * columns('a') := columns('b') }",
            "fn f() { return columns('a') := columns('b') }",
            "fn f() { return * x := y }",
            "fn f() { return *x := y }",
            # Guard cases that should *not* shorten:
            "fn f() { return X := Y }",       # NamedArgument inside return
            "fn f() { return a.b := c }",     # No valid prefix; bare return
            "fn f() { return * }",            # Bare asterisk
            "fn f() { return *columns('a') }",  # No `:=`; full SpreadExpr
        )
        for src in cases:
            oracle = clear_locations(parse_program(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_program(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_interpolate_as_lambda_value(self):
        # `interpolateExpr: columnExpr (AS columnExpr)?` — both sides
        # are full `columnExpr`s, so the AS-value may be a lambda
        # (`LAMBDA y: y+1` or `y -> y+1`). cpp's ALL(*) sees the
        # lambda body after AS and backtracks the alias alternative;
        # rust's Pratt parser greedy-folded `a AS LAMBDA` into a
        # ColumnExprAlias before the outer INTERPOLATE rule got the
        # AS, leaving the lambda body stranded.
        cases = (
            "SELECT 1 ORDER BY x INTERPOLATE (a AS LAMBDA y: y+1)",
            "SELECT 1 ORDER BY x INTERPOLATE (a AS y -> y+1)",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")
        # Guard: AS with a non-lambda RHS still folds as an alias
        # (`AS 5` in INTERPOLATE keeps AS for the outer); AS with
        # a regular identifier RHS is a normal column alias.
        for src in (
            "SELECT a AS my_alias FROM t",
            'SELECT a AS "my alias" FROM t',
            "SELECT 1 ORDER BY x INTERPOLATE (a AS 5)",
        ):
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_hogqlx_tag_in_from_paren_decorations(self):
        # `(<Tag/>)` parses as `LPAREN joinExpr RPAREN` where the inner
        # `joinExpr → tableExpr → hogqlxTagElement`. Per the grammar:
        #   - Inside the parens: `tableExpr (alias | AS identifier)` and
        #     `JoinExprTable (... FINAL? sampleClause?)` bind to the tag.
        #   - Outside the parens: the wrapper is `JoinExprParens` (a
        #     joinExpr alt), not a `tableExpr` — alias / FINAL / SAMPLE
        #     cannot bind (same root cause as the parens-alias fix).
        # Rust had a `(<Tag />)` shortcut that returned a bare tag,
        # bypassing both sides — accepting outer decorations and
        # rejecting inner ones.
        from posthog.hogql.errors import BaseHogQLError

        accept = (
            "SELECT 1 FROM (<Tag /> AS y)",
            "SELECT 1 FROM (<Tag /> JOIN b ON x)",
            "SELECT 1 FROM (<Tag /> FINAL)",
        )
        for src in accept:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

        reject = (
            "SELECT 1 FROM (<Tag />) AS x",
            "SELECT 1 FROM (<Tag />) x",
            "SELECT 1 FROM (<Tag />) FINAL",
        )
        for src in reject:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)

    def test_hogqlx_tag_text_accepts_arbitrary_non_brace_non_lt(self):
        # cpp's `HOGQLX_TEXT_TEXT: ~[<{]+` — any byte except `<` and `{`
        # is valid tag-body text. Rust's mode-less lexer rejected `&`,
        # `!`, `@`, etc. when pre-loading peek1 across the `>` / `/>` /
        # closing `>` boundary, before `consume_hogqlx_text` could
        # byte-walk the body.
        cases = (
            "<a>foo&bar</a>",
            "<a>foo!</a>",
            "<a>foo@bar</a>",
            "<a>1 + 2</a>",
            "<a>!@#%^*()</a>",
            "<outer><inner>foo!bar</inner>baz&qux</outer>",
        )
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_hogqlx_tag_identifier_allows_hyphens(self):
        # The grammar's `HOGQLX_TAG_OPEN` / `HOGQLX_TAG_CLOSE` lexer modes
        # (`HogQLLexer.common.g4:315 + 326`) admit
        # `[a-zA-Z_][a-zA-Z0-9_-]*` for tag names AND attribute names,
        # so hyphens are part of the identifier inside tag delimiters.
        # Rust's mode-less lexer split `a-b` into Ident-Dash-Ident, and
        # `parse_hogqlx_identifier` returned only the first chunk.
        cases = (
            "<a-b />",
            "<a-b-c />",
            "<my-tag a-b={1}>x</my-tag>",
            "<tag a-b={1}/>",
            "<tag><my-child/></tag>",
            "<a-b>{1}</a-b>",
        )
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_join_expr_parens_does_not_take_outer_alias(self):
        # Grammar:
        #   joinExpr  : ... | LPAREN joinExpr RPAREN  # JoinExprParens
        #   tableExpr : ... | tableExpr (alias | AS identifier) columnAliases?
        #                                            # TableExprAlias
        # `TableExprAlias` requires a `tableExpr` head — `LPAREN joinExpr
        # RPAREN` is a `joinExpr`, not a `tableExpr`. cpp rejects the
        # alias / FINAL / SAMPLE after the closing paren; rust was
        # attaching the alias onto the inner JoinExpr.
        from posthog.hogql.errors import BaseHogQLError

        invalid = (
            "SELECT 1 FROM (t) AS x",
            "SELECT 1 FROM (t) x",
            "SELECT 1 FROM ((t)) AS x",
            "SELECT 1 FROM (t JOIN b ON x) AS y",
            "SELECT 1 FROM (t) FINAL",
        )
        for src in invalid:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
        # Guards: subquery and non-parenthesised aliases still parse.
        valid = (
            "SELECT 1 FROM t",
            "SELECT 1 FROM t AS x",
            "SELECT 1 FROM (SELECT 1)",
            "SELECT 1 FROM (SELECT 1) AS x",
        )
        for src in valid:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_string_literal_unknown_backslash_escapes_rejected(self):
        # `ESCAPE_CHAR_COMMON` (`HogQLLexer.common.g4:145`) is a closed
        # set: `\b \f \r \n \t \0 \a \v \\ \xNN`, plus `\'` (escape
        # quote) inside a STRING_LITERAL. Anything else — `\g`, `\u…`,
        # `\1`, bare `\x` without two hex digits — is a lexer error.
        # Rust's `lex_string` silently accepted any two-byte escape,
        # keeping `\g` as literal `\g` etc.
        from posthog.hogql.errors import BaseHogQLError

        invalid = (
            r"'\x'",       # \x without two hex digits
            r"'\g'",       # unknown escape letter
            "'\\u00AB'",   # \u not in cpp grammar
            r"'\1'",       # \1 not in cpp grammar
            r"'\999'",     # \9 not in cpp grammar
        )
        for src in invalid:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
        # Guard: every grammar-allowed escape still parses.
        valid = (
            r"'\n'",
            r"'\t'",
            r"'\\'",
            r"'\''",
            r"'\xAB'",
            r"'\b'",
            r"'\xFF'",
        )
        for src in valid:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_sample_clause_leading_dot_float_value(self):
        # Leading-dot floats (`.5`, `.04`) are valid `floatingLiteral`s
        # in the grammar (`DOT DECIMAL_LITERAL E?...`). The lexer
        # tokenises them as `Dot` + `Number`, so the SAMPLE ratio gate
        # must admit `Dot` when it leads a Number.
        # (NaN-bearing case kept finite — NaN != NaN under == comparison.)
        cases = (
            "SELECT 1 FROM t SAMPLE .5",
            "SELECT 1 FROM t SAMPLE .04",
            "SELECT 1 FROM t SAMPLE .5 / 2",
            "SELECT 1 FROM t SAMPLE 1 / .04",
        )
        for src in cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_sample_clause_only_accepts_number_literals(self):
        # `ratioExpr: placeholder | numberLiteral (SLASH numberLiteral)?`
        # — each side of the ratio is a `numberLiteral`, not a generic
        # `columnExpr`. Rust's `consume_ratio_value` called the prefix
        # parser so Fields, TupleAccess, and placeholder-as-RHS all
        # landed in the ratio slot.
        from posthog.hogql.errors import BaseHogQLError

        invalid = (
            "SELECT * FROM t SAMPLE a",
            "SELECT * FROM t SAMPLE x.y",
            "SELECT * FROM t SAMPLE 1/{p}",
            "SELECT * FROM t SAMPLE 1+1",
        )
        for src in invalid:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
        # Guard: every grammar-allowed SAMPLE form still parses.
        valid = (
            "SELECT * FROM t SAMPLE 1",
            "SELECT * FROM t SAMPLE 1/2",
            "SELECT * FROM t SAMPLE {p}",
            "SELECT * FROM t SAMPLE 0.5",
            "SELECT * FROM t SAMPLE 1 OFFSET 2",
        )
        for src in valid:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_join_op_grammar_alts_validation(self):
        # `joinOp` has three disjoint alts (`HogQLParser.g4:127-134`):
        # JoinOpInner, JoinOpLeftRight, JoinOpFull. Each keyword appears
        # at most once per alt, and the three alts don't share INNER /
        # LEFT / RIGHT / FULL. Rust's source-order loop set booleans
        # without de-duplicating or cross-validating, so it accepted
        # `INNER LEFT`, `LEFT OUTER LEFT`, `FULL INNER`, etc.
        from posthog.hogql.errors import BaseHogQLError

        invalid = (
            "SELECT 1 FROM a INNER LEFT JOIN b ON 1",
            "SELECT 1 FROM a INNER OUTER JOIN b ON 1",
            "SELECT 1 FROM a INNER INNER JOIN b ON 1",
            "SELECT 1 FROM a LEFT OUTER LEFT JOIN b ON 1",
            "SELECT 1 FROM a FULL INNER JOIN b ON 1",
        )
        for src in invalid:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
        # Guard: every grammar-allowed JOIN op still parses.
        valid = (
            "SELECT 1 FROM a JOIN b ON 1",
            "SELECT 1 FROM a INNER JOIN b ON 1",
            "SELECT 1 FROM a LEFT JOIN b ON 1",
            "SELECT 1 FROM a RIGHT JOIN b ON 1",
            "SELECT 1 FROM a LEFT OUTER JOIN b ON 1",
            "SELECT 1 FROM a FULL JOIN b ON 1",
            "SELECT 1 FROM a FULL OUTER JOIN b ON 1",
            "SELECT 1 FROM a INNER ALL JOIN b ON 1",
            "SELECT 1 FROM a ALL INNER JOIN b ON 1",
            "SELECT 1 FROM a ASOF JOIN b ON 1",
            "SELECT 1 FROM a ASOF LEFT JOIN b ON 1",
        )
        for src in valid:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_capital_F_template_string_only_in_full_template_context(self):
        # The grammar has two template-string tokens:
        #   `QUOTE_SINGLE_TEMPLATE: 'f\'' -> pushMode(IN_TEMPLATE_STRING);`
        #   `QUOTE_SINGLE_TEMPLATE_FULL: 'F\'' -> pushMode(IN_FULL_TEMPLATE_STRING);`
        # The lowercase `f'` is reachable from `templateString` (a valid
        # `columnExpr`); the uppercase `F'` is reachable only via the
        # `fullTemplateString` entry rule (e.g. SQL template files), never
        # as a column expression. Rust's lexer collapsed both into the same
        # token and the parser accepted `F'…'` anywhere `f'…'` is allowed.
        from posthog.hogql.errors import BaseHogQLError

        for src in ("F'hello'", "F''", "F'{1+2}'"):
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
        # Guard: lowercase form remains a valid column expression.
        for src in ("f'hello'", "f'{1+2}'"):
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_empty_paren_only_clauses_rejected(self):
        # Three places where the grammar requires at least one body element
        # when parens are present, but rust was accepting bare `()`:
        #   `columnAliases: LPAREN identifier (COMMA identifier)* RPAREN`
        #   `interpolateClause: INTERPOLATE (LPAREN interpolateExpr (COMMA
        #     interpolateExpr)* RPAREN)?`
        #   `columnsReplaceList: columnsReplaceItem (COMMA
        #     columnsReplaceItem)*` (no trailing comma)
        from posthog.hogql.errors import BaseHogQLError

        invalid_select = (
            "SELECT * FROM t AS x ()",
            "SELECT 1 ORDER BY x INTERPOLATE ()",
        )
        for src in invalid_select:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)

        invalid_expr = (
            "COLUMNS(* REPLACE (b AS c,))",
            "COLUMNS(* EXCLUDE (a) REPLACE (b AS c,))",
        )
        for src in invalid_expr:
            for backend in ("cpp-json", "rust-json", "python"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)

        # Guards: populated / bare-keyword forms still parse.
        for src in (
            "SELECT * FROM t AS x (a)",
            "SELECT * FROM t AS x (a, b)",
            "SELECT 1 ORDER BY x INTERPOLATE (a AS b)",
            "SELECT 1 ORDER BY x INTERPOLATE",
        ):
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")
        for src in (
            "COLUMNS(* REPLACE (a AS b, c AS d))",
            "COLUMNS(* REPLACE (a AS b))",
        ):
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_bare_zero_x_prefix_lexes_as_zero_plus_ident(self):
        # `HEXADECIMAL_LITERAL: '0' X HEX_DIGIT+` — the grammar requires
        # at least one hex digit after `0x`. Rust's `lex_number` was
        # committing the `0x` prefix unconditionally and emitting an
        # empty-body hex token, so `SELECT 0x AS y` lexed as `0x AS y`
        # (an empty hex aliased to `y`) instead of `0 x AS y` (which cpp
        # rejects because `x` is an ident in mid-expression position).
        from posthog.hogql.errors import BaseHogQLError

        cases = (
            "SELECT 0x AS y",
            "SELECT 0x + 1",
        )
        for src in cases:
            with self.assertRaises((BaseHogQLError, SyntaxError), msg=src):
                parse_select(src, backend="cpp-json")
            with self.assertRaises((BaseHogQLError, SyntaxError), msg=src):
                parse_select(src, backend="rust-json")
            with self.assertRaises((BaseHogQLError, SyntaxError), msg=src):
                parse_select(src, backend="python")
        # Valid hex literals (≥ 1 hex digit) must keep working.
        for src in ("SELECT 0x1", "SELECT 0xFF", "SELECT 0xaB"):
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_cast_type_param_group_mode_classification(self):
        # cpp's ANTLR commits an `IDENT(...)` type expression to a single
        # alternative — Nested / Complex / Param / Enum — based on what's
        # inside. Param (visited via `ctx->getText()`) preserves case,
        # keeps quoted identifiers' quotes, and concatenates spacelessly.
        # Complex / Nested (recursive visit) lowercases idents and joins
        # with `, `. The Rust parser was deciding mode per-item, so a mix
        # of `#1` + a type-shaped sibling rendered the type-shaped sibling
        # with `, ` joining instead of the Param-mode spaceless form.
        cases = (
            # All items expr-shaped — Param mode end-to-end.
            "cast(x as DateTime64(3, 'UTC'))",
            'cast(x as DateTime64(3, "UTC"))',
            "cast(x as Foo(#1, ABC))",
            # Mixed: `#1` forces Param mode for the whole group, so the
            # sibling `Bar(a, b)` is rendered via getText (spaceless +
            # case-preserved).
            "cast(x as Foo(#1, Bar(a, b)))",
            "cast(x as Foo(Bar(a, b), #1))",
            "cast(x as Foo(#1, f(g(a, b), h(c, d))))",
            # Depth-1 `8` inside `FixedString(8)` doesn't escalate the
            # outer Foo to Param — Foo stays Complex.
            "cast(x as Foo(FixedString(8)))",
            "cast(x as Foo(g(#1)))",
            # All items type-shaped — Complex mode (lowercased + `, `).
            "cast(x as Foo(a(b, c), d))",
            "cast(x as Tuple(a Int, b Int))",
            # Top-level operator forces Param mode.
            "cast(x as Foo(a, b*c))",
            # Per-item raw fallback: `case when (c) then d end` has no
            # depth-0 expression markers (the `(c)` lives at depth 1),
            # but it's not a valid type — cpp resolves to Param.
            "cast(x as Foo(case when (c) then d end))",
        )
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_cast_type_compound_loop_stops_at_non_identifier_keyword(self):
        # cpp's `columnTypeExpr` compound alt is `identifier identifier+`,
        # routed through the `identifier` rule that omits NULL / INF /
        # NAN. So `cast(x as Int NULL)` doesn't form a 2-token type — cpp
        # parses `Int` and then chokes on the trailing `NULL` at the
        # outer `)`. The Rust compound loop used to admit any Keyword,
        # silently eating the trailing `NULL` and emitting `int null` as
        # the type name.
        # `Array(Int NULL)` deliberately omitted: it routes through the
        # parametric-type Param fallback (cpp's `ColumnTypeExprParam`'s
        # raw-text `getText()` render), and bare-keyword recovery there
        # is its own separate problem.
        for src in (
            "cast(x as Int NULL)",
            "cast(x as Int NOT NULL)",
            "cast(x as Int32 NULL)",
            "cast(x as UInt64 NOT NULL)",
            "try_cast(x as Int NULL)",
        ):
            with self.assertRaises(ExposedHogQLError, msg=src):
                parse_expr(src, backend="cpp-json")
            with self.assertRaises(ExposedHogQLError, msg=src):
                parse_expr(src, backend="rust-json")
        # Guards: the valid compound and nested forms must still parse.
        for src in (
            "cast(x as Int)",
            "cast(x as Decimal(10, 2))",
            "cast(x as Array(Int))",
            "cast(x as Time With Time Zone)",
            "cast(x as Foo Bar Baz)",
            "cast(x as Foo Not Bar)",
        ):
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_call_arg_select_releases_when_followed_by_keyword_infix(self):
        # `f((SELECT 1) IN [1, 2])` is a call whose first arg is the
        # comparison `(SELECT 1) IN [1, 2]`, not the SELECT alone. The
        # Rust call-arg parser tried the select-set-stmt arm first and
        # then checked `infix_bp` / `postfix_bp` for a continuing operator;
        # those don't cover the keyword-led infixes (IN, LIKE, ILIKE, IS,
        # BETWEEN, and their NOT-prefixed variants), so the select arm
        # kept the SELECT instead of letting the columnExpr arm take it.
        cases = (
            "f((SELECT 1) IN [1, 2])",
            "f((SELECT 1) NOT IN [1, 2])",
            "f((SELECT 1) LIKE 'x')",
            "f((SELECT 1) NOT LIKE 'x')",
            "f((SELECT 1) ILIKE 'x')",
            "f((SELECT 1) NOT ILIKE 'x')",
            "f((SELECT 1) IS NULL)",
            "f((SELECT 1) IS NOT NULL)",
            "f((SELECT 1) BETWEEN 1 AND 2)",
            "f((SELECT 1) NOT BETWEEN 1 AND 2)",
        )
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")
        # Guard: the bare-SELECT call-argument shape still works.
        for src in ("f((SELECT 1))", "f(SELECT 1)"):
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_named_argument_admits_identifier_shaped_keywords(self):
        # cpp's `ColumnExprNamedArg: identifier COLONEQUALS columnExpr`
        # admits the full `identifier` rule. `true` / `false` lex to plain
        # IDENTIFIERs in cpp (the lexer has no TRUE / FALSE tokens), and
        # soft keywords like `select` / `return` pass through `keyword`.
        # The Rust call-arg fast-path gated on Ident / QuotedIdent only,
        # so `f(true := 1)` fell through and choked on the trailing `:=`.
        cases = (
            "f(true := 1)",
            "f(false := 1)",
            "f(select := 1)",
            "f(return := 1)",
            # quoted-ident path stays the same
            'f("x" := 1)',
            "f(x := 1)",
        )
        for src in cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")
        # NULL / INF / NAN aren't in cpp's `identifier` rule and must
        # stay rejected by both backends.
        for src in ("f(null := 1)", "f(inf := 1)", "f(nan := 1)"):
            with self.assertRaises(ExposedHogQLError, msg=src):
                parse_expr(src, backend="cpp-json")
            with self.assertRaises(ExposedHogQLError, msg=src):
                parse_expr(src, backend="rust-json")

    def test_null_inf_nan_rejected_in_hog_identifier_slots(self):
        # cpp's `varDecl`, `funcStmt`, `catchBlock`, `forInStmt`, and the
        # lambda heads (`columnLambdaExpr` arrow + `ColumnExprColonLambda`)
        # all use the grammar's `identifier` rule, which OMITS NULL / INF /
        # NAN (and the Hog-statement keywords) from its keyword alternative.
        # cpp rejects these positions; Rust used to match `Keyword(_)`
        # indiscriminately and accept them, producing a divergent AST.
        program_cases = (
            "let null := 1",
            "let inf := 1",
            "let nan := 1",
            "for (let null in xs) {}",
            "for (let a, null in xs) {}",
            "fn null() {}",
            "fn f(null) {}",
            "fn f(inf) {}",
            "fn f(nan) {}",
            "fun null() {}",
            "fun f(null) {}",
            "try {} catch (null) {}",
            "try {} catch (e: null) {}",
            "try {} catch (null: T) {}",
            "try {} catch (inf) {}",
            "(null) -> 1",
            "(a, null) -> 1",
            "null -> 1",
            "lambda null: 1",
            "lambda a, null: 1",
        )
        for src in program_cases:
            with self.assertRaises(ExposedHogQLError, msg=src):
                parse_program(src, backend="cpp-json")
            with self.assertRaises(ExposedHogQLError, msg=src):
                parse_program(src, backend="rust-json")
        # And ensure the still-valid identifier-shaped slots keep parsing.
        valid_cases = (
            ("let true := 1", "program"),
            ("let select := 1", "program"),
            ("for (let k, v in xs) {}", "program"),
            ("fn f(x, y) {}", "program"),
            ("try {} catch (e) {}", "program"),
            ("try {} catch (e: T) {}", "program"),
            ("(x, y) -> x + y", "expr"),
            ("x -> x", "expr"),
            ("lambda x: x", "expr"),
        )
        for src, kind in valid_cases:
            parse_fn = parse_program if kind == "program" else parse_expr
            oracle = clear_locations(parse_fn(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_fn(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")

    def test_true_false_admitted_as_identifier_in_chain_and_table_positions(self):
        # cpp's lexer has no TRUE/FALSE tokens; those source spellings are plain
        # IDENTIFIERs that the visitor lifts into Bool Constants only in the
        # bare-Field branch. In positions that route through `keywordForAlias`
        # or identifier-text rules (postfix `.`, table identifiers, CTE column
        # lists), `true`/`false` round-trip as ordinary identifiers. The Rust
        # `kw_valid_as_identifier` predicate used to exclude them.
        expr_cases = ("x.true", "x.false", "x.true.false")
        for src in expr_cases:
            oracle = clear_locations(parse_expr(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_expr(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")
        select_cases = (
            "SELECT * FROM x.true",
            "SELECT * FROM x.false",
            "WITH x(true, false) AS (SELECT 1, 2) SELECT * FROM x",
        )
        for src in select_cases:
            oracle = clear_locations(parse_select(src, backend="cpp-json"))
            for backend in ("rust-json", "python"):
                got = clear_locations(parse_select(src, backend=backend))
                self.assertEqual(got, oracle, msg=f"{backend}: {src!r}")
