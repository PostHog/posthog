"""SQL-injection-defense regression suite for the HogQL printer.

Trust model: every AST string field that reaches printer output is either escape-wrapped (via `_print_identifier`, `_print_escaped_string`, or `context.add_value` parameterization) or interpolated verbatim against an allowlist enforced at both construction (`__post_init__`) and print time. Hog-only nodes compile to HogVM bytecode and never reach a SQL printer; out of scope here.

Tests cover (1) construction-time rejection, (2) printer-side rejection when a value is `setattr`-written past `__post_init__`, (3) branch-only print-time allowlists for fields without a `__post_init__` gate, (4) parser → printer round-trip escape preservation under malicious-looking source content, and (5) cross-backend parser uniformity on grammar quirks that produce out-of-allowlist values.
"""

from typing import Optional

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError, ImpossibleASTError, QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast


def _print(
    self_: BaseTest, query: ast.SelectQuery | ast.SelectSetQuery, *, dialect: HogQLDialect = "clickhouse"
) -> tuple[str, HogQLContext]:
    """Resolve + print, return (sql, context). Inspect `context.values` for parameterized string content."""
    context = HogQLContext(team_id=self_.team.pk, enable_select_queries=True)
    sql, _ = prepare_and_print_ast(query, context, dialect)
    return sql, context


def _select_parse_resolve_mutate_print(
    self_: BaseTest,
    base_query: str,
    mutate_fn,
) -> Optional[str]:
    """Parse + type-resolve a base query, apply `mutate_fn` to the resolved AST, then print. The resolve step is needed because the printer asserts on unresolved FROM-clause types."""
    parsed = parse_select(base_query)
    context = HogQLContext(team_id=self_.team.pk, enable_select_queries=True)
    from posthog.hogql.printer.utils import prepare_ast_for_printing, print_prepared_ast

    prepared = prepare_ast_for_printing(parsed, context=context, dialect="clickhouse")
    assert prepared is not None
    mutate_fn(prepared)
    return print_prepared_ast(prepared, context=context, dialect="clickhouse")


class TestVerbatimFieldConstructionRejection(BaseTest):
    """Group 1: `__post_init__` rejects out-of-allowlist values at construction."""

    @parameterized.expand(
        [
            ("sql_injection", "; DROP TABLE events --"),
            ("union_injection", "JOIN UNION SELECT 1"),
            ("not_in_allowlist", "WEIRD JOIN"),
            ("uppercase_no_join", "LEFT"),
        ]
    )
    def test_join_type_rejects_invalid(self, _name: str, value: str):
        with self.assertRaises(ValueError):
            ast.JoinExpr(table=ast.Field(chain=["events"]), join_type=value)

    @parameterized.expand(
        [
            ("sql_injection", "ASC; DROP TABLE events --"),
            ("wrong_case", "asc"),
            ("not_an_order", "RANDOM"),
            ("empty", ""),
        ]
    )
    def test_order_rejects_invalid(self, _name: str, value: str):
        with self.assertRaises(ValueError):
            # The whole point: pass an out-of-Literal value and verify `__post_init__` rejects it.
            ast.OrderExpr(expr=ast.Constant(value=1), order=value)  # type: ignore[arg-type]

    @parameterized.expand(
        [
            ("sql_injection", "ON; DROP TABLE events --"),
            ("wrong_case", "on"),
            ("not_a_type", "WHERE"),
            ("empty", ""),
        ]
    )
    def test_constraint_type_rejects_invalid(self, _name: str, value: str):
        with self.assertRaises(ValueError):
            ast.JoinConstraint(expr=ast.Constant(value=True), constraint_type=value)  # type: ignore[arg-type]

    @parameterized.expand(
        [
            ("sql_injection", "UNION ALL; DROP TABLE events --"),
            ("not_a_set_op", "JOIN"),
            ("empty", ""),
            ("lowercase", "union all"),
        ]
    )
    def test_set_operator_rejects_invalid(self, _name: str, value: str):
        with self.assertRaises(ValueError):
            ast.SelectSetNode(
                select_query=ast.SelectQuery(select=[ast.Constant(value=1)]),
                set_operator=value,  # type: ignore[arg-type]
            )


class TestVerbatimFieldPrinterDefenseInDepth(BaseTest):
    """Group 2: printer rejects malicious values written via `setattr` past `__post_init__`."""

    def test_join_type_setattr_bypass_rejected_by_printer(self):
        # Parse with the JOIN already present so type resolution attaches a JoinType to next_join; the mutation targets the resolved field directly.
        def mutate(node: ast.SelectQuery) -> None:
            assert node.select_from is not None and node.select_from.next_join is not None
            node.select_from.next_join.join_type = "LEFT JOIN; DROP TABLE events --"

        with self.assertRaises(QueryError):
            _select_parse_resolve_mutate_print(
                self,
                "SELECT 1 FROM events LEFT JOIN events e2 ON 1 = 1",
                mutate,
            )

    def test_order_setattr_bypass_rejected_by_printer(self):
        def mutate(node: ast.SelectQuery) -> None:
            assert node.order_by is not None
            # Deliberate bypass of the `Literal["ASC", "DESC"]` type; the printer's allowlist is what this test exercises.
            node.order_by[0].order = "ASC; DROP TABLE events --"  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        with self.assertRaises(QueryError):
            _select_parse_resolve_mutate_print(self, "SELECT 1 FROM events ORDER BY 1 ASC", mutate)

    def test_constraint_type_setattr_bypass_rejected_by_printer(self):
        def mutate(node: ast.SelectQuery) -> None:
            assert node.select_from is not None and node.select_from.next_join is not None
            assert node.select_from.next_join.constraint is not None
            # Deliberate bypass of the `Literal["ON", "USING"]` type.
            node.select_from.next_join.constraint.constraint_type = "ON; DROP TABLE events --"  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        with self.assertRaises(QueryError):
            _select_parse_resolve_mutate_print(
                self,
                "SELECT 1 FROM events LEFT JOIN events e2 ON 1 = 1",
                mutate,
            )

    def test_set_operator_setattr_bypass_rejected_by_printer(self):
        def mutate(node) -> None:
            assert isinstance(node, ast.SelectSetQuery)  # `... UNION ALL ...` parses to a SelectSetQuery
            # Deliberate bypass of the `SetOperator` Literal type.
            node.subsequent_select_queries[0].set_operator = "UNION ALL; DROP TABLE events --"  # type: ignore[assignment]

        with self.assertRaises(QueryError):
            _select_parse_resolve_mutate_print(
                self,
                "SELECT 1 FROM events UNION ALL SELECT 2 FROM events",
                mutate,
            )


class TestPrintTimeOnlyAllowlists(BaseTest):
    """Group 3: fields without `__post_init__`; the printer's branch check is the only allowlist gate."""

    def test_array_join_op_invalid_rejected_at_print_time(self):
        def mutate(node: ast.SelectQuery) -> None:
            node.array_join_op = "ARRAY JOIN; DROP TABLE events --"
            node.array_join_list = [ast.Field(chain=["x"])]

        with self.assertRaises(ImpossibleASTError):
            _select_parse_resolve_mutate_print(self, "SELECT 1 FROM events", mutate)

    def test_window_frame_type_invalid_rejected_at_print_time(self):
        # `WindowFrameExpr.frame_type` has no `__post_init__`; the printer branch falls through to `ImpossibleASTError` on values outside `Literal["CURRENT ROW", "PRECEDING", "FOLLOWING"]`.
        def mutate(node: ast.SelectQuery) -> None:
            call = node.select[0]
            assert isinstance(call, ast.WindowFunction) and call.over_expr is not None
            assert call.over_expr.frame_start is not None
            call.over_expr.frame_start.frame_type = "FOLLOWING; DROP TABLE--"  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

        with self.assertRaises(ImpossibleASTError):
            _select_parse_resolve_mutate_print(
                self,
                "SELECT count() OVER (ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) FROM events",
                mutate,
            )


class TestEscapePreservationOnParserOutput(BaseTest):
    """Group 4: escape-wrapped paths preserve attacker-controlled content as escaped literals — `Constant.value` (str) lands in `context.values` (CH driver binds it), `Field.chain` identifiers backtick-wrap with embedded-backtick escape via `escape_clickhouse_identifier`."""

    def test_string_constant_with_injection_chars_is_parameterized_not_inlined(self):
        # Dangerous string content lands in `context.values` (a parameter slot, escaped at bind time by the CH driver), not in the SQL body itself.
        sql, context = _print(self, parse_select("SELECT 'evil''; DROP TABLE events; --'"))
        self.assertNotIn("DROP TABLE", sql)
        self.assertIn("evil'; DROP TABLE events; --", context.values.values())

    def test_string_constant_with_control_chars_does_not_leak_into_sql(self):
        # Whatever subset of `\n` / `\t` / `\0` survives the HogQL parser must end up in `context.values`, not embedded in the emitted SQL where a raw newline / tab could terminate the statement.
        sql, context = _print(self, parse_select("SELECT '\\n\\t\\0'"))
        self.assertNotIn("\n", sql)
        self.assertNotIn("\t", sql)
        self.assertNotIn("\0", sql)
        self.assertGreaterEqual(len(context.values), 1)

    def test_identifier_with_backtick_is_backtick_escaped(self):
        # HogQL accepts backtick-quoted identifiers with doubled inner backticks; printer re-emits backtick-wrapped with the inner backtick backslash-escaped.
        sql, _ = _print(self, parse_select("SELECT 1 AS `weird``name` FROM events"))
        self.assertIn("`weird\\`name`", sql)

    def test_identifier_with_percent_rejected(self):
        # `%` is reserved for parameter placeholders downstream; every identifier escape path rejects it.
        with self.assertRaises((QueryError, ExposedHogQLError)):
            _print(self, parse_select("SELECT 1 AS `bad%percent` FROM events"))

    def test_identifier_with_semicolon_in_backticks_escaped_not_executed(self):
        # A semicolon inside a backtick-wrapped identifier lexes as part of the identifier — the backtick scope keeps it from terminating the statement.
        sql, _ = _print(self, parse_select("SELECT 1 AS `id; DROP TABLE events; --`"))
        self.assertIn("`id; DROP TABLE events; --`", sql)


class TestParserPathProducesOnlyAllowlistedVerbatimValues(BaseTest):
    """Group 5: every parser backend rejects grammar-quirk inputs that would produce out-of-allowlist verbatim-printed values."""

    def test_left_outer_semi_join_rejected_by_all_paths(self):
        # `LEFT OUTER SEMI JOIN` passes the rust grammar's per-keyword checks but isn't in `VALID_JOIN_TYPES`; cpp / rust-json reject via the JSON deserializer's `cls(**kwargs)`, rust-py rejects via `PyEmitter::set_field` re-running `__post_init__`.
        q = "SELECT 1 FROM a LEFT OUTER SEMI JOIN b ON a.x = b.x"
        for backend in ("cpp-json", "rust-json", "rust-py"):
            with self.assertRaises((ValueError, ExposedHogQLError)):
                parse_select(q, backend=backend)
