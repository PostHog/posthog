"""SQL-injection-defense regression suite for the HogQL printer.

Locks in the trust model audited in PR #59573:

1. AST string fields fall into three groups:
   - Escape-wrapped at print time (`_print_identifier`, `_print_escaped_string`, `context.add_value` parameterization) — safe regardless of content.
   - Interpolated VERBATIM into emitted SQL — must be allowlisted at both construction (`__post_init__`) and print time (defense-in-depth, catches `setattr`-bypass).
   - Hog-only nodes (HogVM bytecode, never SQL) — out of scope.

2. The parser must not produce verbatim-printed values outside the allowlists.

These tests cover construction, the `setattr`-bypass print path, branch-only print-time allowlists, and the parser → printer round-trip for escape-wrapped fields under malicious-looking source content.
"""

from typing import Optional

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError, ImpossibleASTError, QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast


def _print(
    self_: BaseTest, query: ast.SelectQuery | ast.SelectSetQuery, *, dialect: str = "clickhouse"
) -> tuple[str, HogQLContext]:
    """Run the full resolve + print pipeline and return (sql, context). The context's `values` dict is where parameterized strings land, so callers can inspect it for escape preservation."""
    context = HogQLContext(team_id=self_.team.pk, enable_select_queries=True)
    sql, _ = prepare_and_print_ast(query, context, dialect)
    return sql, context


def _select_parse_resolve_mutate_print(
    self_: BaseTest,
    base_query: str,
    mutate_fn,
) -> Optional[str]:
    """Parse a valid base query, type-resolve it, mutate the resolved AST via `mutate_fn`, then print. Returns the printed SQL (callers expect this path to raise, so the return is rarely used)."""
    parsed = parse_select(base_query)
    context = HogQLContext(team_id=self_.team.pk, enable_select_queries=True)
    # Resolve first so the printer can visit the FROM clause (it asserts on unresolved types).
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
            ast.OrderExpr(expr=ast.Constant(value=1), order=value)

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
            ast.JoinConstraint(expr=ast.Constant(value=True), constraint_type=value)

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
                set_operator=value,
            )


class TestVerbatimFieldPrinterDefenseInDepth(BaseTest):
    """Group 2: printer catches a malicious value written via `setattr`.

    These exercise the gap that `__post_init__`-only validation leaves open. A caller (a test, a transform, a future code path) that mutates a dataclass attribute after construction would otherwise smuggle whatever string they want into the emitted SQL.
    """

    def test_join_type_setattr_bypass_rejected_by_printer(self):
        # Parse with the JOIN already present so type resolution attaches a JoinType to next_join; we just mutate the resolved field.
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
            # Whole point of this test is the deliberate bypass — the Literal type is what the printer's defense backstops.
            node.order_by[0].order = "ASC; DROP TABLE events --"  # ty: ignore[invalid-assignment]

        with self.assertRaises(QueryError):
            _select_parse_resolve_mutate_print(self, "SELECT 1 FROM events ORDER BY 1 ASC", mutate)

    def test_constraint_type_setattr_bypass_rejected_by_printer(self):
        def mutate(node: ast.SelectQuery) -> None:
            assert node.select_from is not None and node.select_from.next_join is not None
            assert node.select_from.next_join.constraint is not None
            # Deliberate bypass — see comment on the order-bypass test above.
            node.select_from.next_join.constraint.constraint_type = "ON; DROP TABLE events --"  # ty: ignore[invalid-assignment]

        with self.assertRaises(QueryError):
            _select_parse_resolve_mutate_print(
                self,
                "SELECT 1 FROM events LEFT JOIN events e2 ON 1 = 1",
                mutate,
            )

    def test_set_operator_setattr_bypass_rejected_by_printer(self):
        def mutate(node) -> None:
            # parse returns a SelectSetQuery for `... UNION ALL ...`.
            assert isinstance(node, ast.SelectSetQuery)
            node.subsequent_select_queries[0].set_operator = "UNION ALL; DROP TABLE events --"

        with self.assertRaises(QueryError):
            _select_parse_resolve_mutate_print(
                self,
                "SELECT 1 FROM events UNION ALL SELECT 2 FROM events",
                mutate,
            )


class TestPrintTimeOnlyAllowlists(BaseTest):
    """Group 3: fields without `__post_init__` whose only gate is the printer's branch check.

    These rely on `ImpossibleASTError` / `QueryError` at print time to reject AST that was synthesized directly (no construction-time defense). The branch checks are sufficient today; these tests pin the behavior so a future printer refactor can't quietly remove the checks.
    """

    def test_array_join_op_invalid_rejected_at_print_time(self):
        def mutate(node: ast.SelectQuery) -> None:
            node.array_join_op = "ARRAY JOIN; DROP TABLE events --"
            node.array_join_list = [ast.Field(chain=["x"])]

        with self.assertRaises(ImpossibleASTError):
            _select_parse_resolve_mutate_print(self, "SELECT 1 FROM events", mutate)

    def test_window_frame_type_invalid_rejected_at_print_time(self):
        # WindowFrameExpr.frame_type has no __post_init__; the printer's branch falls through to ImpossibleASTError on unknown values. Mutate an existing valid frame to a malicious value.
        def mutate(node: ast.SelectQuery) -> None:
            call = node.select[0]
            assert isinstance(call, ast.WindowFunction) and call.over_expr is not None
            assert call.over_expr.frame_start is not None
            # Deliberate bypass — Literal["CURRENT ROW", "PRECEDING", "FOLLOWING"] | None is exactly what the printer's branch backstops.
            call.over_expr.frame_start.frame_type = "FOLLOWING; DROP TABLE--"  # ty: ignore[invalid-assignment]

        with self.assertRaises(ImpossibleASTError):
            _select_parse_resolve_mutate_print(
                self,
                "SELECT count() OVER (ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) FROM events",
                mutate,
            )


class TestEscapePreservationOnParserOutput(BaseTest):
    """Group 4: escape-wrapped paths preserve attacker-controlled content as escaped literals.

    `Constant.value` (str) is parameterized into `context.values[...]`; the SQL contains a `%(hogql_val_N)s` placeholder. The string is rendered safely at bind time by the ClickHouse driver. Verifying the literal lands in `values` (not in the SQL body) is sufficient to confirm the escape.

    `Field.chain` identifiers go through `escape_clickhouse_identifier`, which backtick-wraps and escapes embedded backticks.
    """

    def test_string_constant_with_injection_chars_is_parameterized_not_inlined(self):
        sql, context = _print(self, parse_select("SELECT 'evil''; DROP TABLE events; --'"))
        # The dangerous string lands in context.values, not in the emitted SQL.
        self.assertNotIn("DROP TABLE", sql)
        self.assertIn("evil'; DROP TABLE events; --", context.values.values())

    def test_string_constant_with_control_chars_does_not_leak_into_sql(self):
        # The HogQL parser interprets the backslash sequences; whichever subset survives the parser lands in `context.values` (parameterized), not in the emitted SQL. The threat being closed is "raw newline / tab terminates the SQL statement" — verify the SQL has no embedded control chars regardless of how many the parser preserved.
        sql, context = _print(self, parse_select("SELECT '\\n\\t\\0'"))
        self.assertNotIn("\n", sql)
        self.assertNotIn("\t", sql)
        self.assertNotIn("\0", sql)
        # And there's at least one parameterized value carrying *something* (the parser dropped or preserved it).
        self.assertGreaterEqual(len(context.values), 1)

    def test_identifier_with_backtick_is_backtick_escaped(self):
        # HogQL accepts backtick-quoted identifiers with doubled inner backticks; the printer re-emits backtick-wrapped with the inner backtick backslash-escaped.
        sql, _ = _print(self, parse_select("SELECT 1 AS `weird``name` FROM events"))
        self.assertIn("`weird\\`name`", sql)

    def test_identifier_with_percent_rejected(self):
        # `%` is reserved for parameter placeholders downstream — every escape path rejects identifiers containing it.
        with self.assertRaises((QueryError, ExposedHogQLError)):
            _print(self, parse_select("SELECT 1 AS `bad%percent` FROM events"))

    def test_identifier_with_semicolon_in_backticks_escaped_not_executed(self):
        # An identifier containing a semicolon is backtick-wrapped so the inner content can't terminate the SQL statement — the dangerous chars sit inside `` ` `` ... `` ` `` and lex as part of the identifier in ClickHouse.
        sql, _ = _print(self, parse_select("SELECT 1 AS `id; DROP TABLE events; --`"))
        self.assertIn("`id; DROP TABLE events; --`", sql)


class TestParserPathProducesOnlyAllowlistedVerbatimValues(BaseTest):
    """Group 5: the parser must never emit verbatim-printed values outside the allowlist on any backend (cpp-json / rust-json / rust-py)."""

    def test_left_outer_semi_join_rejected_by_all_paths(self):
        # `LEFT OUTER SEMI JOIN` passes the rust parser's grammar checks but isn't in VALID_JOIN_TYPES. cpp / rust-json reach the dataclass via `cls(**kwargs)` so `__post_init__` rejects. rust-py used to `setattr` post-construction (bypassing the check); `set_field` now re-runs `__post_init__` for `join_type`.
        q = "SELECT 1 FROM a LEFT OUTER SEMI JOIN b ON a.x = b.x"
        for backend in ("cpp-json", "rust-json", "rust-py"):
            with self.assertRaises((ValueError, ExposedHogQLError)):
                parse_select(q, backend=backend)
