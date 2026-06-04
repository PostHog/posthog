from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events, materialized

from parameterized import parameterized

from posthog.schema import MaterializationMode, PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import HogQLQueryModifiers
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.clickhouse import ClickHousePrinter
from posthog.hogql.printer.utils import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.resolver import resolve_types
from posthog.hogql.transforms.property_lowering import (
    lower_properties,
    lower_property_type,
    resolve_materialized_property_source,
)
from posthog.hogql.transforms.property_types import build_property_swapper
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.client import sync_execute
from posthog.models import PropertyDefinition


class TestResolveMaterializedPropertySource(ClickhouseTestMixin, BaseTest):
    def _property_type(
        self, query: str, modifiers: HogQLQueryModifiers | None = None
    ) -> tuple[ast.PropertyType, HogQLContext]:
        context = HogQLContext(
            team_id=self.team.pk,
            database=Database.create_for(team=self.team),
            enable_select_queries=True,
            modifiers=modifiers or HogQLQueryModifiers(),
        )
        resolved = resolve_types(parse_select(query), context, dialect="clickhouse")
        assert isinstance(resolved, ast.SelectQuery)
        select_item = resolved.select[0]
        if isinstance(select_item, ast.Alias):
            select_item = select_item.expr
        assert isinstance(select_item, ast.Field)
        assert isinstance(select_item.type, ast.PropertyType)
        return select_item.type, context

    def test_no_materialization_returns_none(self):
        # No physical backing -> None, so the printer falls back to JSONExtract over the blob.
        property_type, context = self._property_type("SELECT properties.tier FROM events")
        assert resolve_materialized_property_source(property_type.field_type, "tier", context) is None

    def test_property_group_source_under_optimized(self):
        property_type, context = self._property_type(
            "SELECT properties.tier FROM events",
            HogQLQueryModifiers(propertyGroupsMode=PropertyGroupsMode.OPTIMIZED),
        )
        source = resolve_materialized_property_source(property_type.field_type, "tier", context)
        assert source is not None
        assert source.kind == "property_group"
        assert "properties_group" in source.column
        assert source.is_nullable is True

    def test_materialized_column_takes_priority(self):
        with materialized("events", "tier") as mat_col:
            property_type, context = self._property_type(
                "SELECT properties.tier FROM events",
                HogQLQueryModifiers(propertyGroupsMode=PropertyGroupsMode.OPTIMIZED),
            )
            source = resolve_materialized_property_source(property_type.field_type, "tier", context)
            assert source is not None
            assert source.kind == "materialized_column"
            assert source.column == mat_col.name

    def test_disabled_materialization_returns_none(self):
        with materialized("events", "tier"):
            property_type, context = self._property_type(
                "SELECT properties.tier FROM events",
                HogQLQueryModifiers(materializationMode="disabled"),
            )
            assert resolve_materialized_property_source(property_type.field_type, "tier", context) is None


class TestLowerPropertyTypeResultEquivalence(ClickhouseTestMixin, BaseTest):
    """Lowering a `properties.$x` access must return the same rows the ClickHouse printer would.

    For each materialization mode we print the access two ways against the same context — the printer's own
    `visit_property_type`, and our lowered AST — then execute both fragments against ClickHouse and compare.
    Both read the same physical source, so equality is the real proof that the lowered AST is result-equivalent
    to the printer string (which it can never byte-match: the printer uses a `? :` ternary and literal constants).
    """

    def setUp(self):
        super().setUp()
        # tier present / empty-sentinel / absent, plus a nested object for deep-chain extraction.
        _create_event(
            team=self.team,
            distinct_id="u1",
            event="e",
            properties={"tier": "gold", "count": "5", "nested": {"inner": "deep"}},
        )
        _create_event(team=self.team, distinct_id="u2", event="e", properties={"tier": "", "count": "0"})
        _create_event(team=self.team, distinct_id="u3", event="e", properties={})
        flush_persons_and_events()

    def _resolve(self, query: str, modifiers: HogQLQueryModifiers | None = None):
        context = HogQLContext(
            team_id=self.team.pk,
            database=Database.create_for(team=self.team),
            enable_select_queries=True,
            modifiers=modifiers or HogQLQueryModifiers(),
        )
        resolved = resolve_types(parse_select(query), context, dialect="clickhouse")
        assert isinstance(resolved, ast.SelectQuery)
        build_property_swapper(resolved, context)
        return resolved, context

    def _property_field(self, resolved: ast.SelectQuery) -> tuple[ast.Field, ast.PropertyType]:
        item = resolved.select[0]
        if isinstance(item, ast.Alias):
            item = item.expr
        assert isinstance(item, ast.Field)
        assert isinstance(item.type, ast.PropertyType)
        return item, item.type

    def _print(self, expr: ast.Expr, context: HogQLContext, resolved: ast.SelectQuery) -> str:
        return ClickHousePrinter(context=context, stack=[resolved]).visit(expr)

    def _execute(self, fragment: str, context: HogQLContext) -> list:
        rows = sync_execute(
            f"SELECT {fragment} AS v FROM events WHERE team_id = %(team_id)s ORDER BY distinct_id",
            {**context.values, "team_id": self.team.pk},
        )
        return [row[0] for row in rows]

    def _assert_equivalent(self, query: str, modifiers: HogQLQueryModifiers | None = None) -> list:
        resolved, context = self._resolve(query, modifiers)
        field, property_type = self._property_field(resolved)

        baseline_sql = self._print(field, context, resolved)
        lowered_expr = lower_property_type(property_type, context)
        assert lowered_expr is not None, f"expected {query!r} to lower under {modifiers}"
        lowered_sql = self._print(lowered_expr, context, resolved)

        baseline_rows = self._execute(baseline_sql, context)
        lowered_rows = self._execute(lowered_sql, context)
        assert baseline_rows == lowered_rows, (
            f"mismatch for {query!r} ({modifiers}):\n  baseline {baseline_sql} -> {baseline_rows}\n"
            f"  lowered  {lowered_sql} -> {lowered_rows}"
        )
        return lowered_rows

    @parameterized.expand(
        [
            ("json_fallback", None),
            ("auto_default", HogQLQueryModifiers()),
            ("groups_enabled", HogQLQueryModifiers(propertyGroupsMode=PropertyGroupsMode.ENABLED)),
            ("groups_optimized", HogQLQueryModifiers(propertyGroupsMode=PropertyGroupsMode.OPTIMIZED)),
            (
                "legacy_null_as_string",
                HogQLQueryModifiers(materializationMode=MaterializationMode.LEGACY_NULL_AS_STRING),
            ),
        ]
    )
    def test_single_key_equivalent(self, _name: str, modifiers: HogQLQueryModifiers | None):
        rows = self._assert_equivalent("SELECT properties.tier FROM events", modifiers)
        # gold is the only non-empty value; whatever the mode does for ''/absent, gold must survive.
        assert "gold" in rows

    def test_deep_chain_fallback_equivalent(self):
        rows = self._assert_equivalent("SELECT properties.nested.inner FROM events")
        assert "deep" in rows

    def test_materialized_column_single_key_equivalent(self):
        with materialized("events", "tier"):
            self._assert_equivalent("SELECT properties.tier FROM events")

    def test_materialized_column_legacy_null_as_string_equivalent(self):
        with materialized("events", "tier"):
            self._assert_equivalent(
                "SELECT properties.tier FROM events",
                HogQLQueryModifiers(materializationMode=MaterializationMode.LEGACY_NULL_AS_STRING),
            )

    def test_materialized_column_deep_chain_equivalent(self):
        with materialized("events", "nested"):
            self._assert_equivalent("SELECT properties.nested.inner FROM events")

    def _prepare_and_print(self, query: str) -> tuple[str, HogQLContext, ast.Expr]:
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=HogQLQueryModifiers())
        prepared = prepare_ast_for_printing(parse_select(query), context=context, dialect="clickhouse")
        assert prepared is not None
        return print_prepared_ast(prepared, context=context, dialect="clickhouse"), context, prepared

    def test_transform_lowers_select_and_where_end_to_end(self):
        query = "SELECT properties.tier AS t FROM events WHERE properties.tier != '' ORDER BY distinct_id"

        baseline_sql, baseline_context, _ = self._prepare_and_print(query)
        baseline_rows = sync_execute(baseline_sql, baseline_context.values)

        # Lower the prepared AST, then print/execute it the same way.
        _, lowered_context, prepared = self._prepare_and_print(query)
        lowered_ast = lower_properties(prepared, lowered_context)

        # The transform must leave no PropertyType behind on the lowered accesses.
        collector = _PropertyTypeCollector()
        collector.visit(lowered_ast)
        assert collector.property_types == []

        lowered_sql = print_prepared_ast(lowered_ast, context=lowered_context, dialect="clickhouse")
        lowered_rows = sync_execute(lowered_sql, lowered_context.values)

        assert baseline_rows == lowered_rows
        assert ("gold",) in lowered_rows


class _PropertyTypeCollector(TraversingVisitor):
    def __init__(self) -> None:
        self.property_types: list[ast.PropertyType] = []

    def visit_field(self, node: ast.Field) -> None:
        if isinstance(node.type, ast.PropertyType):
            self.property_types.append(node.type)
        super().visit_field(node)


class TestPropertyLoweringCast(ClickhouseTestMixin, BaseTest):
    """The lowering pass must apply the same scalar cast the property swapper does — verified by typed behaviour.

    Lowering now runs globally in `prepare_ast_for_printing`, so `execute_hogql_query` exercises it. A numeric
    cast makes `> 50` order numerically (excluding the string "9"); without the cast it would order
    lexicographically. The result set is computed from the seed data, so it doesn't depend on the pipeline.
    """

    def setUp(self):
        super().setUp()
        _create_event(team=self.team, distinct_id="a", event="e", properties={"amount": "9", "active": "true"})
        _create_event(team=self.team, distinct_id="b", event="e", properties={"amount": "100", "active": "false"})
        _create_event(team=self.team, distinct_id="c", event="e", properties={"amount": "5", "active": "true"})
        flush_persons_and_events()

    def _define(self, name: str, property_type: str) -> None:
        PropertyDefinition.objects.create(
            team=self.team, name=name, property_type=property_type, type=PropertyDefinition.Type.EVENT
        )

    def test_numeric_property_compares_numerically(self):
        self._define("amount", "Numeric")
        result = execute_hogql_query(
            "SELECT properties.amount FROM events WHERE properties.amount > 50 ORDER BY distinct_id",
            team=self.team,
        )
        # Numeric: only 100 > 50. Lexicographic string compare would wrongly include "9".
        assert [row[0] for row in result.results] == [100.0]
        # The Float64 result type confirms the toFloat coercion was applied (not a raw-string read).
        assert result.types == [("amount", "Nullable(Float64)")]

    def test_numeric_property_values_are_floats(self):
        self._define("amount", "Numeric")
        result = execute_hogql_query(
            "SELECT properties.amount FROM events ORDER BY properties.amount",
            team=self.team,
        )
        assert [row[0] for row in result.results] == [5.0, 9.0, 100.0]

    def test_boolean_property_casts(self):
        self._define("active", "Boolean")
        result = execute_hogql_query(
            "SELECT count() FROM events WHERE properties.active = true",
            team=self.team,
        )
        assert result.results[0][0] == 2
