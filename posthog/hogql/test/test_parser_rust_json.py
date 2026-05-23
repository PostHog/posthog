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
    def test_over_window_name_rejects_hog_statement_keywords(self):
        # A named-window reference (`<call> OVER <name>`) is an `identifier`,
        # which admits only the keywords in cpp's `keyword` rule. The
        # Hog-statement keywords are excluded, so they are not valid window
        # names. rust accepted any keyword there; both backends must reject the
        # excluded ones while still accepting an ordinary keyword or identifier.
        for name in ("finally", "try", "catch", "while", "let", "fn", "fun", "throw"):
            for backend in ("cpp-json", "rust-json"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(f"f() over {name}", backend=backend)
        for name in ("select", "from", "with", "where", "w"):
            for backend in ("cpp-json", "rust-json"):
                parse_expr(f"f() over {name}", backend=backend)

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
