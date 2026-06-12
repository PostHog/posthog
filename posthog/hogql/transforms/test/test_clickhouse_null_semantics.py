from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.uuid import uuid_uint128_expr_to_timestamp_expr_v2
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

JSON_X = (
    "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')"
)


class TestClickHouseNullSemantics(BaseTest):
    maxDiff = None

    def _print(self, query: str | ast.SelectQuery) -> str:
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            modifiers=create_default_modifiers_for_team(self.team),
        )
        node = parse_select(query) if isinstance(query, str) else query
        printed, _ = prepare_and_print_ast(node, context=context, dialect="clickhouse")
        return printed

    def _where_sql(self, query: str | ast.SelectQuery) -> str:
        printed = self._print(query)
        return printed.split(" WHERE ", 1)[1].rsplit(" LIMIT ", 1)[0]

    @parameterized.expand(
        [
            # A raw JSON property read is nullable, so HogQL's two-valued semantics need the explicit wrap.
            (
                "nullable_eq_wraps",
                "SELECT 1 FROM events WHERE properties.x = 'a'",
                f"ifNull(equals({JSON_X}, %(hogql_val_1)s), 0)",
            ),
            (
                "nullable_not_eq_wraps_true",
                "SELECT 1 FROM events WHERE properties.x != 'a'",
                f"ifNull(notEquals({JSON_X}, %(hogql_val_1)s), 1)",
            ),
            (
                "eq_null_becomes_is_null",
                "SELECT 1 FROM events WHERE properties.x = NULL",
                f"isNull({JSON_X})",
            ),
            (
                "not_eq_null_becomes_is_not_null",
                "SELECT 1 FROM events WHERE properties.x != NULL",
                f"isNotNull({JSON_X})",
            ),
            (
                "nullable_not_in_wraps_true",
                "SELECT 1 FROM events WHERE properties.x NOT IN ('a', 'b')",
                f"ifNull(notIn({JSON_X}, tuple(%(hogql_val_1)s, %(hogql_val_2)s)), 1)",
            ),
            # IN already gives HogQL's two-valued answer under transform_null_in: never wrapped.
            (
                "in_stays_bare",
                "SELECT 1 FROM events WHERE properties.x IN ('a', 'b')",
                f"and(equals(events.team_id, {{team_id}}), in({JSON_X}, tuple(%(hogql_val_1)s, %(hogql_val_2)s)))",
            ),
            # The call form of a comparison is lowered exactly like the operator form.
            (
                "call_form_eq_wraps",
                "SELECT 1 FROM events WHERE equals(properties.x, 'a')",
                f"ifNull(equals({JSON_X}, %(hogql_val_1)s), 0)",
            ),
            # BETWEEN over a nullable operand wraps the whole infix expression.
            (
                "between_nullable_wraps",
                "SELECT 1 FROM events WHERE properties.x BETWEEN 'a' AND 'b'",
                f"ifNull({JSON_X} BETWEEN %(hogql_val_1)s AND %(hogql_val_2)s, 0)",
            ),
            # The events timestamp anchors the table's primary key: comparisons against it must stay bare for index
            # pruning, even when a wrapper or projection leaves its resolved type nullable.
            (
                "events_timestamp_stays_bare",
                "SELECT 1 FROM events WHERE timestamp > '2024-01-02'",
                "and(equals(events.team_id, {team_id}), greater(events.timestamp, toDateTime64(%(hogql_val_0)s, 6, %(hogql_val_1)s)))",
            ),
            # indexHint() is an optimizer directive — its result does not matter, and wrapping defeats its purpose.
            (
                "index_hint_stays_bare",
                "SELECT 1 FROM events WHERE indexHint(properties.x = 'a')",
                f"indexHint(equals({JSON_X}, %(hogql_val_1)s))",
            ),
            # Constant comparisons fold; the printer's and() folding then absorbs the constant-true.
            (
                "constant_true_folds_away",
                "SELECT 1 FROM events WHERE 'a' = 'a' AND properties.x = 'b'",
                f"and(equals(events.team_id, {{team_id}}), ifNull(equals({JSON_X}, %(hogql_val_1)s), 0))",
            ),
        ]
    )
    def test_where_clause_lowering(self, _name: str, query: str, expected_in_where: str) -> None:
        where_sql = self._where_sql(query)
        self.assertIn(expected_in_where.format(team_id=self.team.pk), where_sql)

    def test_constant_false_comparison_folds_where_to_zero(self) -> None:
        self.assertEqual(self._where_sql("SELECT 1 FROM events WHERE 1 = 2"), "0")

    def test_sessions_v2_timestamp_expr_stays_bare(self) -> None:
        # The sessions-v2 session-start derivation (built as AST by the session where-clause pushdown; its toUInt64
        # spelling is not exposed in HogQL) — non-nullable, and the table's primary-key derivation.
        select = parse_select("SELECT 1 FROM raw_sessions")
        assert isinstance(select, ast.SelectQuery)
        select.where = ast.CompareOperation(
            op=ast.CompareOperationOp.Gt,
            left=uuid_uint128_expr_to_timestamp_expr_v2(ast.Field(chain=["raw_sessions", "session_id_v7"])),
            right=ast.Constant(value="2024-01-02"),
        )
        where_sql = self._where_sql(select)
        self.assertIn("greater(fromUnixTimestamp(intDiv(toUInt64(bitShiftRight(", where_sql)
        self.assertNotIn("ifNull", where_sql)

    def test_join_constraint_stays_bare(self) -> None:
        printed = self._print("SELECT 1 FROM events e JOIN raw_sessions s ON e.properties.x = s.session_id_v7")
        on_clause = printed.split(" ON ", 1)[1].split(" WHERE ", 1)[0]
        self.assertNotIn("ifNull", on_clause)

    def test_compare_in_select_projection_wraps(self) -> None:
        printed = self._print("SELECT properties.x = 'a' FROM events")
        self.assertIn("SELECT ifNull(equals(", printed)

    def test_prepared_ast_carries_lowered_comparisons(self) -> None:
        # The prepared AST (not just the SQL text) holds the wrap, so later passes and consumers can see it.
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            modifiers=create_default_modifiers_for_team(self.team),
        )
        _, prepared = prepare_and_print_ast(
            parse_select("SELECT 1 FROM events WHERE properties.x = 'a'"), context=context, dialect="clickhouse"
        )
        assert isinstance(prepared, ast.SelectQuery)
        where = prepared.where
        assert isinstance(where, ast.Call)
        self.assertEqual(where.name, "ifNull")
        self.assertIsInstance(where.args[0], ast.CompareOperation)
