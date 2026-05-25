"""Tests for the hand-rolled Rust HogQL parser (`rust-json` backend).

The full parser-behaviour suite lives in `_test_parser.py` and runs
against every backend via `parser_test_factory`. This file only wires
the `rust-json` backend into that suite and lists the cases the Rust
parser does not yet match the C++ reference on.
"""

import pytest
from posthog.test.base import no_memory_leak_check

from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_expr, parse_program, parse_select

from ._test_parser import parser_test_factory

# Cases the Rust parser does not yet match C++ on, tracked for follow-up:
#   - promoted_assignment_target_carries_position: the Rust parser does
#     not yet emit per-node source positions (`start` / `end`) at all —
#     every node comes back position-less. The shared suite tolerates
#     this via `clear_locations`, but this test inspects raw positions.
#     Closing it means threading byte offsets through the whole emit
#     layer — a feature in its own right, not a local fix.
_DEFERRED_EXACT: set[str] = {
    "test_promoted_assignment_target_carries_position",
}


class TestParserRustJson(parser_test_factory("rust-json")):  # type: ignore
    def setUp(self) -> None:
        super().setUp()
        if self._testMethodName in _DEFERRED_EXACT:
            self.skipTest("not yet matched by rust-json")

    def test_empty(self):
        # this test only exists to make pycharm recognise this class as a test class
        # the actual tests are in the parent class
        pass

    def test_invalid_interval_in_block_body_rejected(self):
        # Once `interval` is followed by a primary value it commits to the INTERVAL
        # form: a missing / bad unit is a hard error, never a fall-back to
        # `interval`-as-Field. Inside a Hog `{ … }` block body the fall-back would
        # strand the string as a second statement, so `x -> { interval 'ln' }` would
        # parse as `interval; 'ln'` — accepting input the cpp oracle rejects.
        for backend in ("cpp-json", "rust-json"):
            with self.assertRaises(BaseHogQLError):
                parse_expr("x -> { interval 'ln' }", backend=backend)

    def test_date_timestamp_literal_in_block_body_rejected(self):
        # `DATE STRING` / `TIMESTAMP STRING` (the date/timestamp literal forms) are
        # rejected — cpp parses them but its visitor has no literal node for them.
        # rust must commit to the literal form, not treat `date` / `timestamp` as an
        # identifier and strand the string; otherwise inside a Hog `{ … }` block body
        # `{ date 'x' }` parses as the two statements `date; 'x'` and accepts input
        # the cpp oracle rejects.
        for query in ("x -> { date 'ddg' }", "x -> { timestamp 'x' }"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)

    def test_from_table_implicit_alias_rejected(self):
        # `from <implicit-alias>` in table position is the grammar's
        # ColumnExprInvalidFromImplicitAlias footgun — cpp rejects it. rust
        # parsed `select a, from b, from c` as a comma-join whose second table
        # is `from` aliased `c`, accepting input cpp rejects. `from AS c` (explicit
        # alias) and a plain comma-join (`select a, from b, c`) stay valid.
        for backend in ("cpp-json", "rust-json"):
            with self.assertRaises(BaseHogQLError):
                parse_select("select a, from b, from c", backend=backend)
            parse_select("select a, from b, c", backend=backend)
            parse_select("select a, from b as c", backend=backend)

    def test_invalid_cast_type_param_rejected(self):
        # A parametric type's params are `columnExpr`s. rust's raw-text Param
        # path concatenated tokens verbatim without checking the item parsed as
        # an expression, so `cast(1 as d(()))` (empty group), `d(a() b)`
        # (juxtaposition), and friends were accepted where cpp rejects. Each
        # param must now validate as a columnExpr.
        invalid = [
            "cast(1 as d(()))",
            "cast(1 as d(a() b))",
            "cast(1 as d((),1))",
            "cast(1 as Tuple(()))",
        ]
        for query in invalid:
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
        # Valid parametric-type params still parse on both backends.
        for query in ("cast(1 as d())", "cast(1 as d(#1))", "cast(1 as d([1]))", "cast(1 as Array(Int))"):
            parse_expr(query, backend="cpp-json")
            parse_expr(query, backend="rust-json")

    @no_memory_leak_check
    def test_brace_placeholder_only_positions_reject_dict(self):
        # `tableExpr`, `ratioExpr` (SAMPLE) and the `selectStmtWithParens`
        # placeholder arm all admit only a placeholder `{ columnExpr }`, never
        # a Dict. rust shared one brace parser across these slots and the expr
        # position, so it built a Dict for `{}` / `{k: v}` and accepted input
        # cpp rejects. Each placeholder-only slot must reject the Dict while
        # still accepting the `{x}` placeholder.
        dict_in_placeholder_slot = [
            "select 1 from {}",
            "select 1 from {1: 2}",
            "select 1 from t sample {}",
            "select 1 from t sample {1: 2}",
            "{}",
            "{1: 2}",
            "({})",
        ]
        valid_placeholder = [
            "select 1 from {x}",
            "select 1 from t sample {x}",
            "{x}",
            "({x})",
        ]
        for backend in ("cpp-json", "rust-json"):
            for query in dict_in_placeholder_slot:
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)
            for query in valid_placeholder:
                parse_select(query, backend=backend)

    @no_memory_leak_check
    def test_empty_columns_call_and_star_spread_rejected(self):
        # Empty `columns()` matches no `ColumnExprColumns*` production. rust
        # built an empty-list ColumnsExpr and accepted it; it must instead let
        # bare `columns()` fall back to a function call (cpp's behaviour). The
        # `* columns()` spread is then invalid as a single expression — a
        # for-in iterable / if / while condition — where cpp rejects it too.
        invalid_single_expr = [
            "for (let y in * columns()) {}",
            "while (* columns()) {}",
            "if (* columns()) {}",
        ]
        for query in invalid_single_expr:
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_program(query, backend=backend)
        # `* columns()` as two statements (`*` then a `columns()` call), bare
        # `columns()` / regex / list, and a non-empty `* columns('re')` spread
        # all still parse on both backends.
        valid = [
            "* columns()",
            "columns()",
            "columns('re')",
            "columns(a, b)",
            "for (let y in * columns('re')) {}",
        ]
        for query in valid:
            for backend in ("cpp-json", "rust-json"):
                parse_program(query, backend=backend)

    @no_memory_leak_check
    def test_window_name_rejects_hog_statement_keywords(self):
        # A window name is an `identifier`, which admits only the keywords in
        # cpp's `keyword` rule; the Hog-statement keywords are excluded, so they
        # are not valid window names. rust accepted any keyword there. Both
        # window-name positions are the same `identifier` rule: the `OVER <name>`
        # target and the `WINDOW <name> AS (...)` clause. Both must reject the
        # excluded keywords while still accepting an ordinary keyword/identifier.
        excluded = ("finally", "try", "catch", "while", "let", "fn", "fun", "throw")
        valid = ("select", "from", "with", "where", "w")
        for name in excluded:
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(f"f() over {name}", backend=backend)
                with self.assertRaises(BaseHogQLError):
                    parse_select(f"select 1 from t window {name} as (order by x)", backend=backend)
        for name in valid:
            for backend in ("cpp-json", "rust-json"):
                parse_expr(f"f() over {name}", backend=backend)
                parse_select(f"select 1 from t window {name} as (order by x)", backend=backend)

    @no_memory_leak_check
    def test_materialized_keyword_rejected_as_identifier(self):
        # MATERIALIZED is a lexer keyword used only in `WITH x AS MATERIALIZED
        # (...)`; the grammar's `keyword` rule omits it, so it is not a valid
        # identifier. rust admitted it via `kw_valid_as_identifier` /
        # `kw_acts_as_ident_in_primary`, accepting `x.materialized`,
        # `select materialized`, `exclude(materialized)` etc. where cpp rejects.
        for query in ("x.materialized", "materialized", "columns(* exclude(materialized))"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
        for query in ("select 1 as materialized", "select x from t as materialized", "select materialized from t"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)
        # The legitimate MATERIALIZED keyword usage (CTE materialization) still parses.
        for query in (
            "with x as materialized (select 1) select 1 from x",
            "with x as not materialized (select 1) select 1 from x",
        ):
            for backend in ("cpp-json", "rust-json"):
                parse_select(query, backend=backend)

    @no_memory_leak_check
    def test_bare_star_replace_rejected_outside_wrapper(self):
        # `* REPLACE(...)` is a columnExpr only inside the paren forms
        # `(* REPLACE(...))` / `(* EXCLUDE(...) REPLACE(...))` or `COLUMNS(* REPLACE(...))`.
        # rust accepted a bare `* replace(...)` whenever a `)` followed (e.g. as a
        # function argument or tuple element), since its guard couldn't tell a wrapper
        # paren from a borrowed function-call one. Both must reject the bare form.
        for query in ("full(* replace(a as b))", "* replace(a as b)", "(a, * replace(b as c))"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
        for backend in ("cpp-json", "rust-json"):
            with self.assertRaises(BaseHogQLError):
                parse_select("select * replace(a as b) from t", backend=backend)
        # Wrapped REPLACE forms (including nested) and a bare `* EXCLUDE` still parse.
        valid = [
            "(* replace(a as b))",
            "(* exclude(x) replace(a as b))",
            "columns(* replace(a as b))",
            "((* replace(a as b)))",
            "* exclude(a)",
        ]
        for query in valid:
            for backend in ("cpp-json", "rust-json"):
                parse_expr(query, backend=backend)

    @no_memory_leak_check
    def test_statement_leading_brace_block_vs_call(self):
        # A statement-leading `{...}` is a Block, except when a postfix that
        # cannot itself begin a statement follows the matching `}`: a `.` or an
        # EMPTY `()` make the whole thing one called / accessed expression
        # (`{1}.x`, `{1}()`). A non-empty `(expr)` IS a valid next statement, so
        # the brace stays a Block and the `(expr)` is parsed separately
        # (`{1} (a)` -> Block + ExprStatement). rust merged `{block} (expr)` into
        # a single call. Both accept here, so assert full AST parity (positions
        # included, no clear_locations) rather than just accept/reject.
        for query in (
            "{1} (a)",
            "{} ('b')",
            "{x} ('b')",
            "{1}(a, b)",
            "{1} ('b') ('c')",
            "{1}(a).b",
            "{1}()",
            "{}()",
            "{1}.x",
            "{1:2} ('b')",
            "{1}[1]",
            # `.x` property access forces the call parse, but a leading-dot
            # number `.5` is a valid next statement, so the brace stays a Block.
            "{} .x",
            "{ } .5",
            "{ } .5.5",
        ):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_columns_qualifier_rejects_invalid_identifier_keywords(self):
        # The qualifier before `.*` inside `COLUMNS(...)` is the grammar's
        # `identifier` (`COLUMNS LPAREN identifier DOT ASTERISK ...`), so only
        # keywords admitted by `kw_valid_as_identifier` qualify. rust admitted any
        # keyword there, accepting `columns(try.*)` where cpp rejects. The chain
        # links (`columns(a.try.*)`) are `identifier` too and need the same gate.
        excluded = (
            "try",
            "catch",
            "finally",
            "null",
            "inf",
            "nan",
            "intersect",
            "except",
            "fn",
            "fun",
            "let",
            "while",
            "throw",
            "materialized",
        )
        for name in excluded:
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(f"columns({name}.*)", backend=backend)
        for query in ("columns(a.try.*)", "columns(a.b.catch.*)"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
        # `kw_valid_as_identifier` keywords (and `true`/`false`, plain
        # idents, and multi-level chains) remain valid qualifiers.
        for query in (
            "columns(week.*)",
            "columns(select.*)",
            "columns(interval.*)",
            "columns(true.*)",
            "columns(false.*)",
            "columns(x.*)",
            "columns(a.b.*)",
            "columns(a.b.c.*)",
        ):
            for backend in ("cpp-json", "rust-json"):
                parse_expr(query, backend=backend)

    @no_memory_leak_check
    def test_bare_qualified_star_replace_rejected(self):
        # A bare (unwrapped) `ColumnExprAsterisk` (grammar line 289) admits an
        # optional trailing EXCLUDE but never REPLACE — REPLACE is a columnExpr
        # only inside `columns(...)` / `(*...)`. rust consumed a trailing REPLACE
        # in the bare qualified-asterisk postfix path and silently dropped it,
        # accepting `a.* exclude(z) replace(1 as b)` where cpp rejects.
        for query in (
            "a.* replace(1 as b)",
            "a.* exclude(z) replace(1 as b)",
            "a.b.* exclude(z) replace(1 as b)",
        ):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
        # Exclude-only bare forms and the wrapped REPLACE forms still parse.
        for query in (
            "a.* exclude(z)",
            "a.b.* exclude(z)",
            "a.*",
            "columns(a.* replace(1 as b))",
            "columns(a.* exclude(z) replace(1 as b))",
            "(* exclude(z) replace(1 as b))",
        ):
            for backend in ("cpp-json", "rust-json"):
                parse_expr(query, backend=backend)

    @no_memory_leak_check
    def test_columns_qualified_asterisk_continuation_positions(self):
        # When a qualified asterisk (`a.*`) is the LHS of a postfix call or infix
        # op inside `COLUMNS(...)`, the continuation node's span must start at the
        # qualifier's start, not at the token after the asterisk. rust stamped the
        # call/arith node start at the `(` / operator instead of at `a`, so both
        # accepted but `columns[0].start` diverged. Assert full AST parity
        # (positions included) rather than just accept/reject.
        for query in (
            "columns(a.*(b))",
            "columns(a.b.*(c))",
            "columns(a.* + 1)",
            'columns("iei".*(a.b, c.d))',
            "columns(a.* exclude(z) + 1)",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_within_keyword_rejected_as_identifier(self):
        # WITHIN is a lexer keyword used only in the `within group (...)` clause;
        # the grammar's `keyword` rule omits it, so it is not a valid identifier.
        # rust admitted it via `kw_valid_as_identifier` / `kw_acts_as_ident_in_primary`,
        # accepting `within`, `x.within`, `columns(within.*)` as Fields and, at
        # statement level, `f() within ()` as `f(); within()`. All must reject.
        for query in ("within", "within()", "within + 1", "x.within", "1 as within", "columns(within.*)"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
        for query in ("select within from t", "select 1 as within from t", "select x from t as within"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)
        for query in ("f() within ()", "within ()", "within"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_program(query, backend=backend)
        # The legitimate `within group (...)` clause still parses.
        for backend in ("cpp-json", "rust-json"):
            parse_expr("f() within group (order by x)", backend=backend)
            parse_select("select f() within group (order by x) from t", backend=backend)

    @no_memory_leak_check
    def test_positional_and_tuple_index_decimal_literal_parity(self):
        # `#N` (positional ref) and `a.N` / `a?.N` (tuple access) all take a
        # grammar DECIMAL_LITERAL index. rust's lexer folds hex / octal / float
        # into one Number kind, so it diverged two ways: `#N` OVER-ACCEPTED
        # hex/octal/float (`#0x6`, `#017`, `#1e3` became PositionalRef(0) via
        # `parse().unwrap_or(0)`), while `.N` / `?.N` OVER-REJECTED leading-zero
        # decimals (`a.08`, `a.019`) that cpp accepts because 8 and 9 are not
        # octal digits, so the lexer reads them as DECIMAL not OCTAL. All three
        # now share one `is_decimal_literal()` gate.
        rejected = (
            "#0x6",
            "#0X6",
            "#00",
            "#06",
            "#017",
            "#007",
            "#1e3",
            "a.0x6",
            "a.00",
            "a.06",
            "a.017",
            "a.1e3",
            "a?.06",
            "a?.00",
        )
        for query in rejected:
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
        # Decimal indices parse on both, including leading-zero forms whose digits
        # escape the octal range (`08`, `019`). Assert full AST parity (positions
        # included) rather than just accept/reject.
        accepted = (
            "#0",
            "#6",
            "#08",
            "#019",
            "#10",
            "a.0",
            "a.8",
            "a.08",
            "a.019",
            "a.10",
            "a?.0",
            "a?.08",
            "a?.019",
        )
        for query in accepted:
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_nested_interval_reserves_unit_for_outer(self):
        # `INTERVAL <value> <unit>`: cpp's ALL(*) reserves the trailing unit for
        # the OUTER interval, so a nested INTERVAL in value position never takes
        # the unit-consuming form — it is string-only (`interval '5 day'`) or a
        # Field / call. rust used to let the inner interval eat the unit, which
        # over-rejected `interval interval '5 day' month` / `interval interval -
        # x second` (expr) and over-accepted `interval interval 'jihi' month`
        # (program, split into `interval` + `interval 'jihi' month`). The
        # parenthesised forms were already self-contained. Both accept here, so
        # assert full AST parity (positions included).
        for query in (
            "interval interval second",
            "interval interval - x second",
            "interval interval '5 day' month",
            "interval interval (1) second",
            "interval (interval '5 day') month",
            "interval (interval '5 day' month) second",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )
        # A nested bad-string interval rejects on both: the inner
        # ColumnExprIntervalString can't split into `<count> <unit>`. This must
        # also reject at program level (rust no longer splits it into two
        # statements once the inner string interval errors fatally).
        for query in ("interval interval 'jihi' month", "interval interval x second"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
        for backend in ("cpp-json", "rust-json"):
            with self.assertRaises(BaseHogQLError):
                parse_program("interval interval 'jihi' month", backend=backend)

    @no_memory_leak_check
    def test_select_from_keyword_table_vs_invalid_from_column(self):
        # `FROM implicitAlias # ColumnExprInvalidFromImplicitAlias` is a
        # SELECT-COLUMN footgun only: a bare `from <ident>` in TABLE position is
        # valid (`from b, from c` is table `from` aliased `c`). rust used to (1)
        # over-reject explicit-FROM from-as-table cases via a misdiagnosed
        # join.rs check, and (2) over-accept the trailing-comma `select a, from
        # b, from (c)` because it broke the column list at the FIRST from. cpp's
        # `selectColumnExprListBeforeFrom` makes every `from X` before the LAST
        # one a column; only the final `from` opens the clause. Accepting cases
        # assert full AST parity (positions included).
        accept = (
            # from-as-table in the FROM / join clause (explicit FROM):
            "select a from b, from c",
            "select * from from x",
            "select 1 from a, from b, from(c)",
            "select 1 from a join from b on 1",
            "select 1 from from c",
            "select x from t1, from t2, from t3",
            "select 1 from b as from",
            # the LAST `from` opens the clause; an earlier `from(...)` is a call column:
            "select a, from (b), from (c)",
            # single from / cross-join / subquery / union unaffected:
            "select a, from b",
            "select a, from b, c",
            "select a, from (b), c",
            "select a from b, c",
            "select a, from (select 1 from t), c",
            "select a, from b union all select c from d",
        )
        for query in accept:
            self.assertEqual(
                parse_select(query, backend="cpp-json"),
                parse_select(query, backend="rust-json"),
                msg=query,
            )
        # Two+ top-level `from`s: every `from` before the last is a SELECT
        # column, and a bare `from <ident>` column is the rejected footgun.
        reject = (
            "select from x",
            "select a, from b, from c",
            "select a, from b, from (c)",
            "select a, from b, x, from (c)",
            "select a, from b, from c, from d",
        )
        for query in reject:
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)

    @no_memory_leak_check
    def test_from_trailing_comma_only_after_join_constraint(self):
        # A trailing comma in the FROM clause is valid ONLY as the ON / USING
        # `columnExprList`'s optional `COMMA?` (`a JOIN b ON 1,`); cpp's
        # JoinConstraint span includes it. After a cross / plain / positional
        # join the trailing comma is rejected. rust used to discard any
        # post-join trailing comma (over-accepting `a, b,` / `a join b,`) and
        # ended the constraint span before the comma (a position mismatch on the
        # constrained cases). Accepting cases assert full AST parity (positions).
        accept = (
            "select x from a join b on 1,",
            "select x from a left join b on 1,",
            "select x from a join b using c,",
            "select x from a join b using (c),",
            "select x from (a join b on 1,)",
            "select x from a join b using a, b,",
            # controls (no trailing comma):
            "select x from a, b",
            "select x from a join b on 1",
            "select x from a join b",
            "select x from a, b, c",
        )
        for query in accept:
            self.assertEqual(
                parse_select(query, backend="cpp-json"),
                parse_select(query, backend="rust-json"),
                msg=query,
            )
        # Trailing comma after a cross / plain / positional join (no constraint
        # to own it) rejects on both.
        reject = (
            "select x from a, b,",
            "select x from a cross join b,",
            "select x from a join b,",
            "select x from a positional join b,",
            "select x from a join b on 1, c,",
            "select x from a, from b,",
        )
        for query in reject:
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)

    @no_memory_leak_check
    def test_interval_without_unit_does_not_over_commit(self):
        # cpp commits to the INTERVAL form only for a STRING_LITERAL (the
        # ColumnExprIntervalString alt). `interval <number|ident|quoted-ident>`
        # with NO trailing unit is NOT an interval: cpp backtracks to `interval`
        # as a Field. So at expr level it rejects (trailing tokens) on both, but
        # at PROGRAM level it splits into two statements (`interval` + value).
        # rust used to commit fatally for number/ident/quoted-ident too, which
        # over-rejected the program split.
        for query in ("interval 1", "interval x", 'interval "a"'):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
        # A STRING value still commits (a bad single-token string rejects at both
        # expr and program level — no two-statement split).
        for backend in ("cpp-json", "rust-json"):
            with self.assertRaises(BaseHogQLError):
                parse_program("interval 'a'", backend=backend)
        # A trailing unit still makes it a real interval Call on both backends.
        for query in ("interval 1 day", 'interval "a" day', "interval x day"):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_statement_boundary_splits_incomplete_special_infix_and_postfix(self):
        # At a statement boundary, an INCOMPLETE special-infix (LIKE / BETWEEN /
        # IN / IS) or postfix (`[`) is cpp's "end this statement, start the next"
        # shape, not an error: `week like` -> two Field statements, `"_" between
        # "_"` -> three, `[ ] [ ]` -> two empty-array statements. rust's Pratt
        # loop used to apply the operator greedily and error. These all parse on
        # both backends with identical ASTs (positions included).
        for query in (
            "week like",
            '"_" between "_"',
            "[ ] [ ]",
            "[ ] [ ] [ ]",
            "week and",
            "a in",
            "a is",
        ):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )
        # At EXPRESSION level there is no next statement, so the same incomplete
        # forms stay hard errors on both backends (recovery is statement-only).
        for query in ("week like", "[ ] [ ]", "a between b", '"_" between "_"'):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
        # COMPLETE forms are unaffected — still parse identically on both.
        for query in ("a like b", "a between b and c", "a[b]", "a in (1, 2)", "a is null", "a not like b"):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_not_and_modulo_accept_hogqlx_tag_operand(self):
        # `<` begins a HogQLX tag as well as the less-than operator. In bounded
        # lookahead rust used to always read `<` as less-than, so `not <a/>`
        # stranded the tag (NOT became a Field) and `1 % <a/>` abandoned the
        # modulo. cpp reads the tag operand. Both parse identically here.
        for query in (
            "not <a/>",
            "not <a></a>",
            "[not <a/>]",
            "1 and not <a/>",
            "f(not <a/>)",
            "1 % <a/>",
            "[1 % <a/>]",
            "(1 % <a/>)",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )
        # Genuine less-than / modulo (no tag following) are unchanged.
        for query in ("not < 2", "1 % 2", "1 % x"):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_boolean_literal_numeric_tuple_access_keeps_constant(self):
        # `true.1` / `false.0` are tuple access on the boolean Constant, not a
        # Field chain — cpp keeps Constant(true) as the tuple base. rust used to
        # route every `true.`/`false.` through ident-lead, making the base a
        # Field. `true.x` (chain), `true(1)` (call) and `null.1` are unaffected.
        for query in ("true.1", "false.0", "true.1.2", "true.x", "true(1)", "true", "null.1"):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_select_level_sample_requires_using_except_before_group_by(self):
        # Bare SAMPLE is a SELECT-level clause only in slot 1 (`USING?
        # sampleClause`, before GROUP BY) — and on the FROM table. After
        # GROUP BY / HAVING / QUALIFY the only slot is `USING sampleClause`
        # (USING required); a bare SAMPLE there has no grammar slot, so cpp
        # rejects it. rust used to consume and silently drop it.
        for query in (
            "select 1 from t where x sample 0.1",
            "select 1 from t sample 0.1",
            "select 1 from t prewhere x sample 0.1",
            "select 1 from t qualify z using sample 0.1",
            "select 1 from t group by x using sample 0.1",
        ):
            self.assertEqual(
                parse_select(query, backend="cpp-json"),
                parse_select(query, backend="rust-json"),
                msg=query,
            )
        for query in (
            "select 1 from t group by x sample 0.1",
            "select 1 from t group by x having y sample 0.1",
            "select 1 from t qualify z sample 0.1",
        ):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)

    @no_memory_leak_check
    def test_return_keyword_as_identifier_before_infix_postfix(self):
        # `return` is also a keyword-rule identifier. When it is followed by a
        # pure infix / postfix operator, that operator binds `return` as its
        # LHS, so the line is one exprStmt (`return :: t`, `return.x`, `return
        # -> y`, `return = 1`, `return / 2`), not a bare return that strands the
        # operator. A value-starter keeps the return statement (`return 1`,
        # `return + 1`); a keyword-infix keeps the bare-return split (`return
        # like x` is `return` + `like x`).
        for query in (
            "return -> y",
            "return :: date",
            "return . x",
            "return ?. x",
            "return = 1",
            "return / 2",
            "return || x",
            "return < 2",
            "return != 1",
            "return ?? x",
        ):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )
        for query in ("return 1", "return + 1", "return [1]", "return", "return like x", "return * 2"):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )
        # `.` is special: a leading-dot float (`return .5` -> value 0.5,
        # `return .5.5` -> tuple-access on 0.5) is a return VALUE, while a
        # `.`-chain-link (`return .x`) makes `return` an identifier (tuple /
        # field). Both must match cpp (regression guard for the #16 dispatch).
        for query in ("return .5", "return .5.5", "return . 5", "return .x"):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_not_before_statement_keyword_falls_back_to_field(self):
        # At a statement boundary, `not` followed by a statement keyword that is
        # not a valid expression operand (`let`, `throw`) is `not` as a bare
        # Field statement followed by the keyword's statement — not a NOT whose
        # operand fails. rust used to commit NOT to the operator and reject.
        for query in ("not let x", "not throw x"):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )
        # An incomplete `not let` (no value) or a keyword that is neither a
        # valid operand nor a complete statement still rejects on both.
        for query in ("not let", "not while x", "not fn x"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_program(query, backend=backend)

    @no_memory_leak_check
    def test_block_then_empty_param_lambda_is_two_statements(self):
        # `{…} ()` is a dict / placeholder called with empty args (one
        # exprStmt), but `{…} () -> body` is a Block followed by an empty-param
        # lambda statement (two statements). rust used to force the empty-call
        # interpretation and then reject when the block body was not a dict.
        for query in ("{ } () -> 1", "{ let q := 1; } () -> 1;", "{ if (1) {} } () -> 1"):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )
        # Unchanged: empty call (no arrow), non-empty params, dict, plain block.
        for query in ("{ } ()", "{ 1 } ()", "{ } (a) -> 1", "{ } () + 1", "{1: 2}", "{ let x := 1; }"):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_hogqlx_tag_name_rejects_non_identifier_keywords(self):
        # A HogQLX tag/attr name is a grammar `identifier`, so a keyword head is
        # valid only when the grammar's `keyword` rule admits it. The Hog-statement
        # keywords (fn/fun/let/while/throw/try/catch/finally), set-op keywords
        # (intersect/except), literal keywords (null/inf/nan) and within/materialized
        # are omitted from that rule, so cpp rejects `<fn/>`; rust used to accept
        # them as tag/attr names (over-accept).
        for kw in (
            "fn",
            "fun",
            "let",
            "while",
            "throw",
            "try",
            "catch",
            "finally",
            "intersect",
            "except",
            "null",
            "inf",
            "nan",
            "within",
            "materialized",
        ):
            for query in (f"< {kw} />", f"< a {kw} />"):
                for backend in ("cpp-json", "rust-json"):
                    with self.assertRaises(BaseHogQLError):
                        parse_expr(query, backend=backend)
        # Keywords that the grammar's `keyword` rule admits stay valid tag names.
        for kw in ("and", "select", "from", "by", "group", "order", "day", "sample"):
            self.assertEqual(
                parse_expr(f"< {kw} />", backend="cpp-json"),
                parse_expr(f"< {kw} />", backend="rust-json"),
                msg=kw,
            )

    @no_memory_leak_check
    def test_not_falls_back_to_field_when_operand_invalid(self):
        # In EXPRESSION context cpp's single-expression parse reads a leading NOT
        # as a Field when its operand can't parse, so a following infix binds to
        # it: `not < a` -> `(Field not) < a`, `not + a` -> `(Field not) + a`,
        # `not in a` -> `(Field not) in a`, `not as x` -> `Field(not) AS x`. A bare
        # `not as` keeps `Not(Field('as'))` (the operand parses). rust used to
        # commit NOT to the unary operator and reject. `not in (1,2)` stays the
        # unary `Not(Call(in, …))`.
        for query in (
            "not < a",
            "not + a",
            "not in a",
            "not as",
            "not as x",
            "not as date",
            "not like 'a'",
            "not in (1,2)",
            "not x",
            "a not in b",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )
        # At a STATEMENT boundary cpp takes the shortest leading statement, so
        # `not <op-keyword> <rhs>` is `Not(Field(<kw>))` (statement 1) and `<rhs>`
        # opens the next statement (two declarations), not the greedy single
        # expression. rust used to glue it into one statement.
        for query in (
            "not in a",
            "not like 'a'",
            "not and a",
            "not is null",
            "not * a",
            "not ignore nulls",
        ):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_in_cohort_marker_only_before_a_complete_value(self):
        # `IN COHORT? columnExpr`: cpp takes the COHORT marker only when a complete
        # value follows it. When COHORT is followed by an operator it is the IN rhs
        # Field (or part of the rhs expression): `a in cohort < b` ->
        # `(a in cohort) < b`, `a in cohort like b` -> `(a in cohort) like b`,
        # `a in cohort * b` -> `a in (cohort * b)`. rust used to greedily eat COHORT
        # and choke on the empty / dangling value.
        for query in (
            "a in cohort < b",
            "a in cohort + b",
            "a in cohort * b",
            "a in cohort like b",
            "a in cohort is null",
            "a not in cohort < b",
            "a not in cohort * b",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )
        # COHORT stays a marker before a complete value (a bare `*`, a negative
        # number, a tag, a parenthesised/array value, or a plain primary), and a
        # value followed by an outer infix (`cohort 1 < b`) still works.
        for query in (
            "a in cohort 1",
            "a in cohort x",
            "a in cohort *",
            "a in cohort -1",
            "a in cohort <foo/>",
            "a in cohort (1)",
            "a in cohort [1]",
            "a in cohort 1 < b",
            "a not in cohort 1",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_select_distinct_reread_as_column_when_no_value_follows(self):
        # `SELECT DISTINCT? columnExprList`: DISTINCT is the modifier only when a
        # column follows. When the next token ends the column list (comma / EOF)
        # or opens a clause, cpp re-reads DISTINCT as the sole column Field:
        # `SELECT DISTINCT` -> `[Field(distinct)]`, `SELECT DISTINCT ORDER BY 1` ->
        # `[Field(distinct)]` + ORDER BY. rust used to keep DISTINCT a modifier and
        # then reject on the empty / clause-keyword column slot.
        for query in (
            "SELECT DISTINCT",
            "SELECT DISTINCT, a",
            "SELECT DISTINCT ORDER BY 1",
            "SELECT DISTINCT GROUP BY 1",
            "SELECT DISTINCT WHERE 1",
            "SELECT DISTINCT HAVING 1",
            "SELECT DISTINCT LIMIT 1",
            "SELECT DISTINCT group by 1",
        ):
            self.assertEqual(
                parse_select(query, backend="cpp-json"),
                parse_select(query, backend="rust-json"),
                msg=query,
            )
        # DISTINCT stays the modifier before a real column (incl. a bare keyword
        # column like `group` with no `BY`).
        for query in (
            "SELECT DISTINCT a",
            "SELECT DISTINCT a, b",
            "SELECT DISTINCT *",
            "SELECT DISTINCT day",
            "SELECT DISTINCT group",
        ):
            self.assertEqual(
                parse_select(query, backend="cpp-json"),
                parse_select(query, backend="rust-json"),
                msg=query,
            )
        # `SELECT DISTINCT FROM x` keeps DISTINCT a modifier and rejects on both
        # via the FROM-implicit-alias footgun (DISTINCT is NOT re-read here).
        for backend in ("cpp-json", "rust-json"):
            with self.assertRaises(BaseHogQLError):
                parse_select("SELECT DISTINCT FROM x", backend=backend)

    @no_memory_leak_check
    def test_hogqlx_attribute_and_text_child_positions_match(self):
        # cpp positions each HogQLXAttribute (name start -> value end, or name end
        # for a bare attribute), the string value Constant over the string token,
        # and each text-child Constant over its raw byte span. rust left these
        # inner nodes position-less. The shared suite strips positions, so this
        # asserts exact-position parity (the comparison keeps positions).
        for query in (
            "<a b='1' />",
            "<a b='1' c='2' />",
            "< a and />",
            "<a>x</a>",
            "<a>hello world</a>",
            "<a b='1'>text</a>",
            "<a b={1} />",
            "<outer><inner k='v'>t</inner></outer>",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_lambda_keyword_is_a_plain_alias_after_as(self):
        # The grammar's explicit `AS identifier` admits every keyword, so `AS
        # lambda` is a plain alias `Alias(expr, 'lambda')` in expression context.
        # rust blanket-refused `AS lambda` (it only ever heads a lambda value in
        # `INTERPOLATE (expr AS columnExpr)`), so it rejected the alias. Refuse
        # only when a lambda BODY (`lambda [params] :`) actually follows.
        for query in (
            "1 as lambda",
            "x as lambda",
            "(1) as lambda",
            "1 + 1 as lambda",
            "[1 as lambda]",
            "f(1 as lambda)",
            "1 as lambda()",
            "1 as lambda + 2",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )
        for query in ("select 1 as lambda", "select 1 as lambda, 2", "select 1 as lambda from t"):
            self.assertEqual(
                parse_select(query, backend="cpp-json"),
                parse_select(query, backend="rust-json"),
                msg=query,
            )
        # A real lambda body after `AS` is not a valid alias and rejects on both
        # in plain expression context (the alias absorbs `lambda`, the `:` trails).
        for query in ("1 as lambda: 2", "1 as lambda x: x", "1 as lambda x"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)

    @no_memory_leak_check
    def test_empty_fstring_constant_spans_whole_token(self):
        # An empty f-string `f''` has no interior text, so cpp spans its Constant
        # over the whole `f''` token, not the zero-width gap between the quotes.
        # rust positioned it at the interior; the comparison keeps positions.
        for query in ("f''", "f'a'", "f'ab'", "f'  '", "[f'']", "f'' || f''"):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_interpolate_expr_carries_positions(self):
        # The INTERPOLATE item node (InterpolateExpr) was built without a position
        # wrap, so it came back position-less; cpp spans it from the expr start to
        # the value end (or the expr end when there is no `AS value`).
        for query in (
            "select 1 order by a with fill interpolate (b)",
            "select 1 order by a with fill interpolate (b as 5)",
            "select 1 order by a with fill interpolate (b, c)",
            "select 1 order by a with fill interpolate (b as c, d)",
        ):
            self.assertEqual(
                parse_select(query, backend="cpp-json"),
                parse_select(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_between_span_includes_parenthesized_high_closing_paren(self):
        # A simple BETWEEN spans through the high operand's last consumed token,
        # so a parenthesized `high` (`1 between 2 and (3)`) must include the
        # trailing `)`. rust used `high.end` (the inner expr, parens stripped),
        # leaving the BetweenExpr end one byte short. The comparison keeps
        # positions.
        for query in (
            "1 between (2) and (3)",
            "1 between 2 and (3)",
            "1 between (2) and 3",
            "1 not between 2 and (3)",
            "a between (b) and (c)",
            "1 between (2+3) and (4)",
            "1 between (2) and (3) + 4",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )

    # ---- Known divergences, tracked as xfail (strict) --------------------
    # Each asserts the DESIRED cpp/rust parity and currently fails. strict=True
    # flips a fix to a hard failure so the marker gets removed when the gap closes.

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Irreducible ALL(*) greedy-column artifact. `select 1, from f, using sample 1`: "
            "cpp's `selectColumnExprListBeforeFrom` greedily eats `from f` as a "
            "`ColumnExprInvalidFromImplicitAlias` column (trailing-comma form), leaving "
            "`using sample 1` to match the select-level `(USING? sampleClause)?` clause — "
            "then the from-implicit-alias column rejects. rust's single pass instead opens the "
            "FROM clause at `from f` and consumes `using` as a cross-join table + sample. Both "
            "AGREE on the explicit-from `select 1 from a, using sample 1` (using = cross-join "
            "table); only the leading-comma column/from boundary resolution diverges, which "
            "needs whole-query backtracking to replicate (a general fix, not a 3-condition hack)."
        ),
    )
    @no_memory_leak_check
    def test_xfail_select_leading_comma_keyword_table_sample(self):
        for backend in ("cpp-json", "rust-json"):
            with self.assertRaises(BaseHogQLError):
                parse_select("select 1, from f, using sample 1", backend=backend)

    @no_memory_leak_check
    def test_date_literal_tolerated_in_discarded_set_decorators(self):
        # A `selectSetStmt`'s trailing `orderByClause?` is always grammar-parsed
        # but never emitted by cpp's `VISIT(SelectSetStmt)`, and its trailing
        # LIMIT / OFFSET are dropped when the body is a `{placeholder}` (which
        # can't carry them). cpp never visits those discarded subtrees, so an
        # unsupported `date`/`timestamp` literal anywhere inside (incl. nested
        # selects / calls) is tolerated. rust used to commit to the date literal
        # and fatally reject; the suppression now leaks into the whole discarded
        # subtree, matching cpp.
        for query in (
            "( {x} order by date 'z' )",
            "( {x} order by (select 1 order by date 'z') )",
            "( {x} order by f(date 'z') )",
            "( {x} order by date 'z' + 1 )",
            "( (select 1) order by (select date 'z') )",  # ORDER BY discarded even for a real subquery
            "( {x} order by date 'z' limit 1 )",
            "( {x} limit date 'z' )",  # placeholder LIMIT dropped -> tolerated
            "( {x} offset date 'z' )",
            "( {x} limit date 'z' with ties )",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )
        program = "range := ( { ( 'nlhonme ' ) } order by 'e' , date 'fa' collate 'a' ) "
        self.assertEqual(
            parse_program(program, backend="cpp-json"),
            parse_program(program, backend="rust-json"),
        )
        # Still strict where cpp DOES visit: a real SelectQuery's kept order by /
        # limit / offset, and a bare / placeholder-block date literal. All must
        # reject on both backends (the placeholder LIMIT suppression must not
        # leak to a real `(select …)` body). A set op (UNION / EXCEPT) wraps the
        # result in a decorator-carrying SelectSetQuery, so its LIMIT is KEPT and
        # visited even when the operands are placeholders — the suppression must
        # not fire there either.
        for query, fn in (
            ("select 1 order by date 'x'", parse_select),
            ("select 1 order by (select date 'z')", parse_select),
            ("select 1 limit date 'x'", parse_select),
            ("(select 1) limit date 'x'", parse_select),
            ("(select 1) offset date 'x'", parse_select),
            ("{1} except {2} limit date 'x'", parse_select),
            ("({1}) union all ({2}) limit date 'x'", parse_select),
            ("({1}) except {2} limit interval 'p'", parse_select),
            ("date 'x'", parse_expr),
            ("{ date 'x' }", parse_program),
        ):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError, msg=query):
                    fn(query, backend=backend)

    @no_memory_leak_check
    def test_date_literal_tolerated_in_select_level_sample(self):
        # The `selectStmt` grammar allows a `(USING? sampleClause)?` at SELECT
        # level (two slots), but cpp's `VISIT(SelectStmt)` never reads it — only
        # a TABLE-level sample lands on `JoinExpr.sample`. So an unsupported date
        # literal in a select-level sample's (placeholder) ratio is tolerated;
        # rust used to fatally reject.
        for query in (
            "select 1 using sample { date '' }",
            "select 1 sample { date '' }",
            "select 1 from f using sample { date '' }",
            "select 1 where 1 using sample { date '' }",
            "select 1 group by 1 using sample { date '' }",
        ):
            self.assertEqual(
                parse_select(query, backend="cpp-json"),
                parse_select(query, backend="rust-json"),
                msg=query,
            )
        # A TABLE-level sample IS visited, so its date rejects on both; the
        # suppression must not leak to it.
        for query in ("select 1 from f sample { date '' }", "select 1 from f sample date ''"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError, msg=query):
                    parse_select(query, backend=backend)

    @no_memory_leak_check
    def test_interval_string_without_unit_tolerated_in_unvisited_clause(self):
        # `INTERVAL <string>` with no `<count> <unit>` content is cpp's
        # `ColumnExprIntervalString`, which `visitColumnExprIntervalString`
        # rejects — so it's tolerated in the same clauses cpp grammar-parses but
        # never visits (discarded ORDER BY, a placeholder body's LIMIT, the
        # select-level SAMPLE). rust used to fatally require a unit keyword.
        for query in (
            "{x} order by interval 'pk'",
            "{x} order by interval 'pk' collate ''",
            "{x} order by 1 with fill to interval 'g'",
            "{x} limit interval 'p'",
            "select 1 using sample { interval 'pk' }",
        ):
            self.assertEqual(
                parse_select(query, backend="cpp-json"),
                parse_select(query, backend="rust-json"),
                msg=query,
            )
        # Still strict elsewhere: a KEPT clause visits it, a bare / block form
        # rejects, and a non-string interval value with no unit is a grammar
        # error even when discarded (so the suppression is string-gated).
        strict: list[tuple[str, object]] = [
            ("select 1 order by interval 'pk'", parse_select),
            ("select 1 limit interval 'pk'", parse_select),
            ("interval 'pk'", parse_expr),
            ("{ interval 'ln' }", parse_program),
            ("{x} order by interval 1", parse_select),
            ("{x} order by interval x", parse_select),
        ]
        for query, fn in strict:
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError, msg=query):
                    fn(query, backend=backend)

    @no_memory_leak_check
    def test_stacked_table_alias_span_ends_at_first_alias(self):
        # `TableExprAlias` is left-recursive (`x a b c`): cpp's nested ctxs end
        # the JoinExpr span at the INNERMOST (first) alias, while each outer
        # alias only overwrites `alias` / `column_aliases`. rust extended the
        # span to the last alias. Covers the `t format JSON` FORMAT-as-alias
        # chain and column-alias stacks. (Single / no alias are unchanged.)
        for query in (
            "select 1 from x t",
            "select 1 from x a b",
            "select 1 from x a b c",
            "select 1 from x t format JSON",
            "select 1 from x (c1, c2)",
            "select 1 from x a (c1) b (c2)",
        ):
            self.assertEqual(
                parse_select(query, backend="cpp-json"),
                parse_select(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_between_split_synthetic_node_positions(self):
        # When the greedy BETWEEN-body parse is split at the rightmost AND, the
        # rebuilt And/Or (and the wrappers it descends through) must carry cpp's
        # ctx-derived span, not the children's inner (paren-stripped) span. cpp
        # positions a boolean node from its FIRST operand's `(` and LAST operand's
        # `)`, and a stay-in-place wrapper (Lambda / Not / arith.right / the
        # if-call else-branch) ends where its now-shorter child ends. A no_pos
        # NamedArgument operand still contributes its `value`'s end.
        for query in (
            "x between (1) and (2) or y",  # synthetic Or start = `(` of `(2)`
            "1 between 2 and (3) and 4",  # synthetic And end = `)` of `(3)`
            "x between (1) and lambda z: (2) and (3)",  # Lambda body end shrinks
            "a between not lambda x: (b) and (c) and d",  # Not + Lambda descent
            "x between 1 and (2) * (3) and 4",  # arith.right end shrinks
            "a between b ? c : (d) and (e) and f",  # if-call else-branch end
            "1 between 2 between 3 and (4) and 5",  # nested BETWEEN low peel
            "x between y between z and (w) and v",
            "p between (q) and r := (s) and (t)",  # no_pos NamedArgument last operand
            "m between (n) and o := (p) and q := (r) and (s)",
            "x between (1) and ((2) or (3)) and (4)",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_return_empty_parens_is_a_call(self):
        # `return ()` — empty parens are not a valid return value, so cpp re-reads
        # `return` as a Field and `()` as an empty call: `Call(return, [])`. rust
        # used to commit to the return statement and reject the empty parens. A
        # `return (expr)` (incl. empty `[]` / `{}` which ARE valid values) keeps
        # the returnStmt.
        for query in ("return ()", "return ( )", "return () + 1", "x := return ()", "return () ()"):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )
        for query in ("return (1)", "return (1, 2)", "return []", "return {}", "return"):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )

    @no_memory_leak_check
    def test_bare_star_decorator_splits_at_statement_boundary(self):
        # A bare `*` admits only a valid `EXCLUDE (<identifiers>)` (no REPLACE, no
        # string/empty list). At a statement boundary an invalid decorator is cpp's
        # `*` (or `* EXCLUDE(...)`) statement followed by `exclude(...)` / `replace(...)`
        # as the NEXT statement's call: `* exclude ('j')` -> `*` ; `exclude('j')`,
        # `* replace (1 as b)` -> `*` ; `replace(1 as b)`, `* exclude (a) replace (b as c)`
        # -> `ColumnsExpr(exclude=[a])` ; `replace(b as c)`. rust used to reject.
        for query in (
            "* exclude ('j')",
            "* exclude ()",
            "x := * exclude ('j')",
            "osl := * exclude ()",
            "* replace (1 as b)",
            "* exclude (a) replace (1 as b)",
            "x := * replace (1 as b)",
        ):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )
        # A valid `* EXCLUDE (<idents>)` stays one columns-expr; outside a statement
        # boundary (a SELECT column) an invalid / REPLACE decorator rejects on both,
        # and the paren-wrapped `(* REPLACE …)` form stays valid.
        for query in (
            "select * exclude (a) from t",
            "select (* replace (1 as b)) from t",
        ):
            self.assertEqual(
                parse_select(query, backend="cpp-json"),
                parse_select(query, backend="rust-json"),
                msg=query,
            )
        for query in ("select * exclude ('j') from t", "select * replace (1 as b) from t"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)

    @no_memory_leak_check
    def test_invalid_filter_clause_splits_at_statement_boundary(self):
        # The aggregate FILTER clause requires `(WHERE <expr>)`. An invalid FILTER
        # (`filter ()`, no WHERE) is, at a statement boundary, cpp's completed
        # `<call>()` statement followed by a `filter(...)` call as the NEXT
        # statement: `l() filter ()` -> `l()` ; `filter()` (also for parametric
        # `quantile(0.5)(x) filter ()`). rust used to commit to the clause and
        # reject. A valid `filter (where …)` stays one expression (the clause is
        # consumed and dropped).
        for query in (
            "l() filter ()",
            "count() filter ()",
            "x := l() filter ()",
            "l() filter filter ()",
            "quantile(0.5)(x) filter ()",
        ):
            self.assertEqual(
                parse_program(query, backend="cpp-json"),
                parse_program(query, backend="rust-json"),
                msg=query,
            )
        for query in ("count() filter (where 1)", "sum(x) filter (where y > 1) over ()", "count() over ()"):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )
        # Outside a statement boundary (a SELECT column) the invalid FILTER rejects.
        for backend in ("cpp-json", "rust-json"):
            with self.assertRaises(BaseHogQLError):
                parse_expr("count() filter ()", backend=backend)

    @no_memory_leak_check
    def test_cast_type_enum_vs_param_fallback(self):
        # A cast type `q(...)` is `ColumnTypeExprEnum` only when every entry is a
        # `string '=' numberLiteral` (the visitor then rejects it as unsupported).
        # If any value isn't a numberLiteral (`''`, an ident, `1 + 2`) or the
        # separator is `==`, ANTLR falls back to `ColumnTypeExprParam` (a
        # columnExpr param), which cpp accepts. rust used to commit to the enum
        # path on a `string =` head and reject these.
        for query in (
            "cast(1 as q('a' = ''))",
            "cast(1 as q('a' = 'b'))",
            "cast(1 as q('a' = x))",
            "cast(1 as q('a' = 1 + 2))",
            "cast(1 as q('a' == 1))",
            "cast(1 as q('a' = 1, 'b' = ''))",
            "try_cast(1 as q('a' = ''))",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )
        # A real enumValue list (string '=' numberLiteral, incl. floats / inf /
        # signed / trailing comma) stays ColumnTypeExprEnum and rejects on both.
        for value in ("1", "-1", "1.5", "1.5e3", "2447.9157e+17", "inf", "nan", "0x1f", ".5"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(f"cast(1 as q('a' = {value}))", backend=backend)
        # Non-enum parametric / nested / complex types are unaffected.
        for query in (
            "cast(1 as Decimal(10, 2))",
            "cast(1 as FixedString(5))",
            "cast(1 as Array(Int))",
            "cast(1 as Tuple(UInt8, String))",
        ):
            self.assertEqual(
                parse_expr(query, backend="cpp-json"),
                parse_expr(query, backend="rust-json"),
                msg=query,
            )
