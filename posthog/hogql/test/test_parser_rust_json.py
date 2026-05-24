"""Tests for the hand-rolled Rust HogQL parser (`rust-json` backend).

The full parser-behaviour suite lives in `_test_parser.py` and runs
against every backend via `parser_test_factory`. This file only wires
the `rust-json` backend into that suite and lists the cases the Rust
parser does not yet match the C++ reference on.
"""

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
