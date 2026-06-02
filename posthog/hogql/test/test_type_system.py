from typing import Optional, cast

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import FloatArrayDatabaseField
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types
from posthog.hogql.type_diagnostics import function_catalog_inventory, resolve_with_type_diagnostics
from posthog.hogql.type_system import (
    ComparisonCompatibility,
    comparison_compatibility,
    least_common_supertype,
    parse_clickhouse_type,
    runtime_type_from_database_field,
)
from posthog.hogql.visitor import clone_expr


class TestHogQLTypeSystem:
    maxDiff = None

    def _select(self, query: str, placeholders: Optional[dict[str, ast.Expr]] = None) -> ast.SelectQuery:
        return cast(
            ast.SelectQuery,
            clone_expr(parse_select(query, placeholders=placeholders), clear_locations=True),
        )

    def setup_method(self) -> None:
        self.database = Database()
        self.context = HogQLContext(database=self.database, team_id=1, enable_select_queries=True)

    def _assert_first_column_type(
        self, query: str, expected_type: ast.ConstantType, dialect: HogQLDialect = "clickhouse"
    ) -> None:
        node = cast(ast.SelectQuery, resolve_types(self._select(query), self.context, dialect=dialect))
        column_type = node.select[0].type
        assert column_type is not None
        assert column_type.resolve_constant_type(self.context) == expected_type

    def test_parse_clickhouse_runtime_types(self) -> None:
        parsed = parse_clickhouse_type("Nullable(LowCardinality(Array(Tuple(id UInt64, ts DateTime64(3, 'UTC')))))")

        assert parsed.family == "array"
        assert parsed.nullable is True
        assert parsed.item_type is not None
        assert parsed.item_type.family == "tuple"
        assert parsed.item_type.field_names == ("id", "ts")
        assert parsed.item_type.item_types[0].family == "integer"
        assert parsed.item_type.item_types[0].signed is False
        assert parsed.item_type.item_types[1].family == "datetime"
        assert parsed.item_type.item_types[1].precision == 3
        assert parsed.item_type.item_types[1].timezone == "UTC"

    def test_database_field_runtime_type_preserves_float_array_dimension(self) -> None:
        field = FloatArrayDatabaseField(name="score_bins", nullable=False)

        constant_type = field.get_constant_type()
        runtime_type = runtime_type_from_database_field(field)

        assert constant_type == ast.ArrayType(nullable=False, item_type=ast.FloatType(nullable=False))
        assert runtime_type.family == "array"
        assert runtime_type.item_type is not None
        assert runtime_type.item_type.family == "float"

    def test_least_common_supertype_numeric_array_and_datetime(self) -> None:
        assert least_common_supertype(
            [ast.IntegerType(nullable=False), ast.FloatType(nullable=False)]
        ) == ast.FloatType(nullable=False)
        assert least_common_supertype(
            [
                ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False)),
                ast.ArrayType(nullable=True, item_type=ast.FloatType(nullable=False)),
            ]
        ) == ast.ArrayType(nullable=True, item_type=ast.FloatType(nullable=False))
        assert least_common_supertype(
            [ast.DateType(nullable=False), ast.DateTimeType(nullable=True)]
        ) == ast.DateTimeType(nullable=True)

    def test_comparison_compatibility(self) -> None:
        assert (
            comparison_compatibility(ast.IntegerType(nullable=False), ast.FloatType(nullable=False))
            == ComparisonCompatibility.CHEAP_CAST
        )
        assert (
            comparison_compatibility(ast.StringType(nullable=False), ast.DateTimeType(nullable=False))
            == ComparisonCompatibility.EXPENSIVE_CAST
        )

    def test_resolver_infers_cast_types(self) -> None:
        self._assert_first_column_type(
            "SELECT CAST('2024-01-01 00:00:00' AS DateTime)",
            ast.DateTimeType(nullable=False),
        )
        self._assert_first_column_type(
            "SELECT TRY_CAST('1' AS INTEGER)",
            ast.IntegerType(nullable=True),
            dialect="postgres",
        )

    def test_resolver_infers_array_and_tuple_access_types(self) -> None:
        self._assert_first_column_type("SELECT [1, 2.0][1]", ast.FloatType(nullable=False))

        node = ast.TupleAccess(
            tuple=ast.Tuple(exprs=[ast.Constant(value=1), ast.Constant(value="two")]),
            index=2,
        )
        resolved = cast(ast.TupleAccess, resolve_types(node, self.context, dialect="clickhouse"))
        assert resolved.type == ast.StringType(nullable=False)

    def test_resolver_infers_conditional_and_aggregate_function_types(self) -> None:
        self._assert_first_column_type("SELECT if(true, 1, 2.0)", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT multiIf(true, 1, false, 2.0, 3)", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT coalesce(1, 2.0)", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT count() FROM events", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT sum(1.0) FROM events", ast.FloatType(nullable=False))

    def test_select_set_query_unifies_output_column_types(self) -> None:
        node = cast(
            ast.SelectSetQuery,
            resolve_types(
                self._select("SELECT 1 AS value UNION ALL SELECT 2.0 AS value"), self.context, dialect="clickhouse"
            ),
        )

        assert isinstance(node.type, ast.SelectSetQueryType)
        assert node.type.resolve_column_constant_type("value", self.context) == ast.FloatType(nullable=False)

    def test_type_diagnostics_reports_unknown_function_boundary(self) -> None:
        diagnostics = resolve_with_type_diagnostics(
            self._select("SELECT base64Encode('test')"),
            self.context,
            dialect="clickhouse",
        )

        assert diagnostics.report.unknown_count == 1
        assert diagnostics.report.unknowns_by_source() == {"missing_function_signature": 1}
        assert diagnostics.report.unknowns[0].detail == "base64Encode"

    def test_function_catalog_inventory(self) -> None:
        inventory = function_catalog_inventory()

        assert inventory.total_entries > 0
        assert inventory.entries_by_dialect["clickhouse"] == inventory.total_entries
        assert inventory.entries_with_legacy_signatures > 0
        assert inventory.entries_with_precise_signatures > 0
        assert inventory.aggregate_entries > 0
        assert "base64Encode" in inventory.functions_without_signatures
