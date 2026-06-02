from typing import Optional, cast

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import FloatArrayDatabaseField
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.resolver import resolve_types
from posthog.hogql.transforms.type_aware_simplification import simplify_redundant_type_operations
from posthog.hogql.type_diagnostics import function_catalog_inventory, resolve_with_type_diagnostics
from posthog.hogql.type_system import (
    ComparisonCompatibility,
    comparison_compatibility,
    infer_function_return_type,
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
        assert parsed.low_cardinality is True
        assert parsed.display().startswith("Nullable(LowCardinality(Array(")
        assert parsed.item_type is not None
        assert parsed.item_type.family == "tuple"
        assert parsed.item_type.field_names == ("id", "ts")
        assert parsed.item_type.item_types[0].family == "integer"
        assert parsed.item_type.item_types[0].signed is False
        assert parsed.item_type.item_types[1].family == "datetime"
        assert parsed.item_type.item_types[1].precision == 3
        assert parsed.item_type.item_types[1].timezone == "UTC"

        parsed_map = parse_clickhouse_type("Map(String, Nullable(Float64))")

        assert parsed_map.family == "map"
        assert parsed_map.nullable is False
        assert parsed_map.key_type is not None
        assert parsed_map.key_type.family == "string"
        assert parsed_map.value_type is not None
        assert parsed_map.value_type.family == "float"
        assert parsed_map.value_type.nullable is True

        parsed_state = parse_clickhouse_type("AggregateFunction(sum, Float64)")

        assert parsed_state.family == "aggregate_state"
        assert parsed_state.wrapped_type is not None
        assert parsed_state.wrapped_type.family == "float"

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
        self._assert_first_column_type("SELECT accurateCast('1', 'Int64')", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT accurateCastOrNull('1', 'Int64')", ast.IntegerType(nullable=True))
        self._assert_first_column_type("SELECT accurateCast('2024-01-01', 'Date')", ast.DateType(nullable=False))
        self._assert_first_column_type("SELECT accurateCast('1', 'Nullable(Int64)')", ast.IntegerType(nullable=True))
        self._assert_first_column_type("SELECT reinterpretAsUInt64('12345678')", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT reinterpretAsFloat64('12345678')", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT reinterpretAsUUID('1234567890123456')", ast.UUIDType(nullable=False))

    def test_resolver_infers_array_and_tuple_access_types(self) -> None:
        self._assert_first_column_type("SELECT [1, 2.0][1]", ast.FloatType(nullable=False))

        node = ast.TupleAccess(
            tuple=ast.Tuple(exprs=[ast.Constant(value=1), ast.Constant(value="two")]),
            index=2,
        )
        resolved = cast(ast.TupleAccess, resolve_types(node, self.context, dialect="clickhouse"))
        assert resolved.type == ast.StringType(nullable=False)

        self._assert_first_column_type(
            "SELECT tupleElement(JSONExtract('{\"name\":\"Ada\",\"score\":1.5}', 'Tuple(name String, score Float64)'), 'score')",
            ast.FloatType(nullable=False),
        )

    def test_resolver_infers_structural_array_function_types(self) -> None:
        self._assert_first_column_type(
            "SELECT arrayZip([1], ['a'])",
            ast.ArrayType(
                nullable=False,
                item_type=ast.TupleType(
                    nullable=False,
                    item_types=[ast.IntegerType(nullable=False), ast.StringType(nullable=False)],
                ),
            ),
        )
        self._assert_first_column_type(
            "SELECT arrayFlatten([[1], [2.0]])",
            ast.ArrayType(nullable=False, item_type=ast.FloatType(nullable=False)),
        )
        self._assert_first_column_type(
            "SELECT arrayDistinct([1, 2.0])",
            ast.ArrayType(nullable=False, item_type=ast.FloatType(nullable=False)),
        )
        self._assert_first_column_type(
            "SELECT arraySort([1, 2.0])",
            ast.ArrayType(nullable=False, item_type=ast.FloatType(nullable=False)),
        )
        self._assert_first_column_type(
            "SELECT arrayReverse([1, 2.0])",
            ast.ArrayType(nullable=False, item_type=ast.FloatType(nullable=False)),
        )
        self._assert_first_column_type("SELECT arraySum([1, 2])", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT arrayAvg([1, 2])", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT arrayMin([1, 2.0])", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT arrayMax([1, 2.0])", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT arrayReduce('sum', [1, 2.0])", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT arrayReduce('avg', [1, 2])", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT arrayReduce('min', [1, 2.0])", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT arrayReduce('uniq', ['a', 'b'])", ast.IntegerType(nullable=False))

    def test_resolver_infers_map_function_types(self) -> None:
        self._assert_first_column_type(
            "SELECT map('a', 1, 'b', 2.0)",
            ast.MapType(
                nullable=False,
                key_type=ast.StringType(nullable=False),
                value_type=ast.FloatType(nullable=False),
            ),
        )
        self._assert_first_column_type("SELECT map('a', 1)['a']", ast.IntegerType(nullable=False))
        self._assert_first_column_type(
            "SELECT mapFromArrays(['a'], [1, 2.0])",
            ast.MapType(
                nullable=False,
                key_type=ast.StringType(nullable=False),
                value_type=ast.FloatType(nullable=False),
            ),
        )
        self._assert_first_column_type(
            "SELECT mapKeys(map('a', 1))",
            ast.ArrayType(nullable=False, item_type=ast.StringType(nullable=False)),
        )
        self._assert_first_column_type(
            "SELECT mapValues(map('a', 1, 'b', 2.0))",
            ast.ArrayType(nullable=False, item_type=ast.FloatType(nullable=False)),
        )
        self._assert_first_column_type(
            "SELECT mapFilter((k, v) -> v > 1, map('a', 1, 'b', 2))",
            ast.MapType(
                nullable=False,
                key_type=ast.StringType(nullable=False),
                value_type=ast.IntegerType(nullable=False),
            ),
        )
        self._assert_first_column_type(
            "SELECT mapApply((k, v) -> tuple(k, v + 0.5), map('a', 1))",
            ast.MapType(
                nullable=False,
                key_type=ast.StringType(nullable=False),
                value_type=ast.FloatType(nullable=False),
            ),
        )

    def test_resolver_binds_higher_order_map_lambda_argument_types(self) -> None:
        node = cast(
            ast.SelectQuery,
            resolve_types(
                self._select("SELECT mapFilter((k, v) -> v > 1, map('a', 1, 'b', 2))"),
                self.context,
                dialect="clickhouse",
            ),
        )

        call = cast(ast.Call, node.select[0])
        lambda_node = cast(ast.Lambda, call.args[0])
        lambda_type = cast(ast.SelectQueryType, lambda_node.type)
        key_arg = cast(ast.FieldAliasType, lambda_type.aliases["k"])
        value_arg = cast(ast.FieldAliasType, lambda_type.aliases["v"])

        assert key_arg.resolve_constant_type(self.context) == ast.StringType(nullable=False)
        assert value_arg.resolve_constant_type(self.context) == ast.IntegerType(nullable=False)
        assert call.type is not None
        assert call.type.resolve_constant_type(self.context) == ast.MapType(
            nullable=False,
            key_type=ast.StringType(nullable=False),
            value_type=ast.IntegerType(nullable=False),
        )

    def test_resolver_binds_higher_order_array_lambda_argument_types(self) -> None:
        node = cast(
            ast.SelectQuery,
            resolve_types(
                self._select("SELECT arrayMap(x -> x + 0.5, [1, 2])"),
                self.context,
                dialect="clickhouse",
            ),
        )

        call = cast(ast.Call, node.select[0])
        lambda_node = cast(ast.Lambda, call.args[0])
        lambda_type = cast(ast.SelectQueryType, lambda_node.type)
        lambda_arg = cast(ast.FieldAliasType, lambda_type.aliases["x"])

        assert lambda_arg.resolve_constant_type(self.context) == ast.IntegerType(nullable=False)
        assert lambda_node.expr.type is not None
        assert lambda_node.expr.type.resolve_constant_type(self.context) == ast.FloatType(nullable=False)
        assert call.type is not None
        assert call.type.resolve_constant_type(self.context) == ast.ArrayType(
            nullable=False,
            item_type=ast.FloatType(nullable=False),
        )

    def test_resolver_keeps_array_filter_input_element_type(self) -> None:
        self._assert_first_column_type(
            "SELECT arrayFilter(x -> x > 1, [1, 2])",
            ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False)),
        )

    def test_resolver_binds_multi_argument_higher_order_array_lambdas(self) -> None:
        self._assert_first_column_type(
            "SELECT arrayMap((x, y) -> concat(x, y), ['a'], ['b'])",
            ast.ArrayType(nullable=False, item_type=ast.StringType(nullable=False)),
        )
        self._assert_first_column_type(
            "SELECT arrayMap((x, y) -> y, [1], ['b'])",
            ast.ArrayType(nullable=False, item_type=ast.StringType(nullable=False)),
        )

    def test_resolver_infers_json_extract_type_literal(self) -> None:
        self._assert_first_column_type(
            "SELECT JSONExtract('{\"num\": 42}', 'num', 'Int32')",
            ast.IntegerType(nullable=False),
        )
        self._assert_first_column_type(
            "SELECT JSONExtract('[\"ReferenceError\"]', 'Array(String)')",
            ast.ArrayType(nullable=False, item_type=ast.StringType(nullable=False)),
        )
        self._assert_first_column_type(
            "SELECT JSONExtract('{\"score\": 1}', 'Map(String, UInt64)')",
            ast.MapType(
                nullable=False,
                key_type=ast.StringType(nullable=False),
                value_type=ast.IntegerType(nullable=False),
            ),
        )
        self._assert_first_column_type(
            "SELECT JSONExtract('{\"num\": 42}', 'not_a_type')",
            ast.StringType(nullable=False),
        )

    def test_resolver_infers_json_helper_function_types(self) -> None:
        self._assert_first_column_type("SELECT JSONHas('{\"num\": 42}', 'num')", ast.IntegerType(nullable=False))
        self._assert_first_column_type(
            "SELECT JSONLength('{\"items\": [1, 2]}', 'items')", ast.IntegerType(nullable=False)
        )
        self._assert_first_column_type("SELECT JSONType('{\"num\": 42}', 'num')", ast.StringType(nullable=False))
        self._assert_first_column_type("SELECT JSON_VALUE('{\"num\": 42}', '$.num')", ast.StringType(nullable=False))
        self._assert_first_column_type(
            "SELECT JSONExtractUInt('{\"num\": 42}', 'num')", ast.IntegerType(nullable=False)
        )
        self._assert_first_column_type("SELECT JSONExtractInt('{\"num\": 42}', 'num')", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT JSONExtractFloat('{\"num\": 42}', 'num')", ast.FloatType(nullable=False))
        self._assert_first_column_type(
            "SELECT JSONExtractBool('{\"flag\": true}', 'flag')", ast.BooleanType(nullable=False)
        )
        self._assert_first_column_type(
            "SELECT JSONExtractString('{\"name\": \"Ada\"}', 'name')", ast.StringType(nullable=False)
        )
        self._assert_first_column_type("SELECT JSONExtractRaw('{\"num\": 42}', 'num')", ast.StringType(nullable=False))
        self._assert_first_column_type(
            "SELECT JSONExtractKeys('{\"num\": 42}')",
            ast.ArrayType(nullable=False, item_type=ast.StringType(nullable=False)),
        )
        self._assert_first_column_type(
            "SELECT JSONExtractArrayRaw('[1, 2]')",
            ast.ArrayType(nullable=False, item_type=ast.StringType(nullable=False)),
        )
        self._assert_first_column_type(
            "SELECT JSONExtractKeysAndValues('{\"score\": 1}', 'Float64')",
            ast.ArrayType(
                nullable=False,
                item_type=ast.TupleType(
                    nullable=False,
                    item_types=[ast.StringType(nullable=False), ast.FloatType(nullable=False)],
                ),
            ),
        )
        self._assert_first_column_type(
            "SELECT JSONExtractKeysAndValuesRaw('{\"score\": 1}')",
            ast.ArrayType(
                nullable=False,
                item_type=ast.TupleType(
                    nullable=False,
                    item_types=[ast.StringType(nullable=False), ast.StringType(nullable=False)],
                ),
            ),
        )

    def test_json_extract_array_type_binds_higher_order_lambda_argument(self) -> None:
        node = cast(
            ast.SelectQuery,
            resolve_types(
                self._select(
                    "SELECT arrayExists(v -> v = 'ReferenceError', JSONExtract('[\"ReferenceError\"]', 'Array(String)'))"
                ),
                self.context,
                dialect="clickhouse",
            ),
        )

        call = cast(ast.Call, node.select[0])
        lambda_node = cast(ast.Lambda, call.args[0])
        lambda_type = cast(ast.SelectQueryType, lambda_node.type)
        lambda_arg = cast(ast.FieldAliasType, lambda_type.aliases["v"])

        assert lambda_arg.resolve_constant_type(self.context) == ast.StringType(nullable=False)
        assert call.type is not None
        assert call.type.resolve_constant_type(self.context) == ast.BooleanType(nullable=False)

    def test_resolver_infers_conditional_and_aggregate_function_types(self) -> None:
        self._assert_first_column_type("SELECT if(true, 1, 2.0)", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT multiIf(true, 1, false, 2.0, 3)", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT coalesce(1, 2.0)", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT count() FROM events", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT sum(1.0) FROM events", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT uniqIf(distinct_id, true) FROM events", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT argMax('a', 1) FROM events", ast.StringType(nullable=False))
        self._assert_first_column_type("SELECT quantile(0.95)(1) FROM events", ast.FloatType(nullable=False))
        self._assert_first_column_type(
            "SELECT quantiles(0.5, 0.9)(1) FROM events",
            ast.ArrayType(nullable=False, item_type=ast.FloatType(nullable=False)),
        )

    def test_resolver_infers_aggregate_state_and_merge_function_types(self) -> None:
        sum_state = infer_function_return_type("sumState", [ast.FloatType(nullable=False)]).return_type
        assert sum_state == ast.AggregateStateType(
            nullable=False,
            wrapped_type=ast.FloatType(nullable=False),
        )

        assert infer_function_return_type("sumMerge", [sum_state]).return_type == ast.FloatType(nullable=False)
        assert infer_function_return_type(
            "countMerge", [ast.UnknownType(nullable=False)]
        ).return_type == ast.IntegerType(nullable=False)
        assert infer_function_return_type(
            "avgState", [ast.IntegerType(nullable=False)]
        ).return_type == ast.AggregateStateType(
            nullable=False,
            wrapped_type=ast.FloatType(nullable=False),
        )

        quantiles_state = infer_function_return_type("quantilesState", [ast.IntegerType(nullable=False)]).return_type
        assert quantiles_state == ast.AggregateStateType(
            nullable=False,
            wrapped_type=ast.ArrayType(nullable=False, item_type=ast.FloatType(nullable=False)),
        )
        assert infer_function_return_type("quantilesMerge", [quantiles_state]).return_type == ast.ArrayType(
            nullable=False,
            item_type=ast.FloatType(nullable=False),
        )

    def test_resolver_infers_common_string_function_types(self) -> None:
        self._assert_first_column_type("SELECT base64Encode('test')", ast.StringType(nullable=False))
        self._assert_first_column_type("SELECT hex(unhex('DEADBEEF'))", ast.StringType(nullable=False))
        self._assert_first_column_type(
            "SELECT splitByChar('.', '1.2.3')",
            ast.ArrayType(nullable=False, item_type=ast.StringType(nullable=False)),
        )

    def test_resolver_infers_common_url_function_types(self) -> None:
        self._assert_first_column_type("SELECT protocol('https://posthog.com')", ast.StringType(nullable=False))
        self._assert_first_column_type(
            "SELECT extractURLParameter('https://posthog.com/?utm_source=docs', 'utm_source')",
            ast.StringType(nullable=False),
        )
        self._assert_first_column_type(
            "SELECT URLHierarchy('https://posthog.com/docs/hogql')",
            ast.ArrayType(nullable=False, item_type=ast.StringType(nullable=False)),
        )
        self._assert_first_column_type("SELECT port('https://posthog.com:443')", ast.IntegerType(nullable=False))

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
            self._select("SELECT formatReadableSize(1024)"),
            self.context,
            dialect="clickhouse",
        )

        assert diagnostics.report.unknown_count == 1
        assert diagnostics.report.unknowns_by_source() == {"missing_function_signature": 1}
        assert diagnostics.report.unknowns_by_detail() == {"formatReadableSize": 1}
        assert diagnostics.report.optimizer_blocker_count == 1
        assert diagnostics.report.optimizer_blockers_by_source() == {"missing_function_signature": 1}
        assert diagnostics.report.unknowns[0].detail == "formatReadableSize"

    def test_type_diagnostics_treats_typed_string_functions_as_known(self) -> None:
        diagnostics = resolve_with_type_diagnostics(
            self._select(
                "SELECT "
                "base64Encode('test'), "
                "hex(unhex('DEADBEEF')), "
                "splitByChar('.', '1.2.3'), "
                "protocol('https://posthog.com')"
            ),
            self.context,
            dialect="clickhouse",
        )

        assert diagnostics.report.unknown_count == 0

    def test_type_diagnostics_treats_representative_optimizer_queries_as_ready(self) -> None:
        queries = [
            (
                "SELECT "
                "if(equals(protocol('https://posthog.com'), 'https'), toFloat(1), 2.0), "
                "coalesce(JSONExtractString('{\"name\": \"Ada\"}', 'name'), 'unknown')"
            ),
            (
                "SELECT "
                "arrayMap(x -> x + 0.5, JSONExtract('[1, 2]', 'Array(Int64)')), "
                "arrayReduce('sum', [1, 2.0]), "
                "arrayZip([1], ['a'])"
            ),
            ("SELECT mapApply((k, v) -> tuple(k, v + 0.5), map('a', 1)), mapFilter((k, v) -> v > 0, map('a', 1))"),
            ("SELECT count(), sum(toFloat(1)), argMax('a', 1), quantiles(0.5, 0.9)(1) FROM events"),
        ]

        for query in queries:
            diagnostics = resolve_with_type_diagnostics(self._select(query), self.context, dialect="clickhouse")
            assert diagnostics.report.optimizer_blocker_count == 0, query

    def test_function_catalog_inventory(self) -> None:
        inventory = function_catalog_inventory()

        assert inventory.total_entries > 0
        assert inventory.entries_by_dialect["clickhouse"] == inventory.total_entries
        assert inventory.entries_with_legacy_signatures > 0
        assert inventory.entries_with_generic_inference > 0
        assert inventory.entries_with_precise_generic_inference > 0
        assert inventory.entries_with_precise_signatures > 0
        assert inventory.aggregate_entries > 0
        assert "base64Encode" in inventory.functions_without_signatures
        assert "base64Encode" not in inventory.functions_without_type_inference
        assert "protocol" not in inventory.functions_without_type_inference
        assert "formatReadableSize" in inventory.functions_without_type_inference

    def test_type_aware_simplification_is_opt_in(self) -> None:
        resolved = cast(
            ast.SelectQuery,
            resolve_types(self._select("SELECT CAST('x' AS String) AS value"), self.context, dialect="clickhouse"),
        )
        sql = print_prepared_ast(resolved, self.context, dialect="clickhouse")

        assert "toString(" in sql

    def test_type_aware_simplification_removes_redundant_casts_and_null_wrappers(self) -> None:
        resolved = cast(
            ast.SelectQuery,
            resolve_types(
                self._select(
                    "SELECT CAST('x' AS String) AS a, toString('y') AS b, assumeNotNull(1) AS c, ifNull(1, 2) AS d, coalesce(1, 2) AS e, toDateTime(toDateTime('2020-01-01')) AS f"
                ),
                self.context,
                dialect="clickhouse",
            ),
        )
        simplified = simplify_redundant_type_operations(resolved, self.context, dialect="clickhouse")
        sql = print_prepared_ast(simplified, self.context, dialect="clickhouse")

        assert "toString(" not in sql
        assert "assumeNotNull(" not in sql
        assert "ifNull(" not in sql
        assert "coalesce(" not in sql
        assert "toDateTime(toDateTime(" not in sql
        assert "1 AS c" in sql
        assert "1 AS d" in sql
        assert "1 AS e" in sql

    def test_type_aware_simplification_keeps_unsafe_casts(self) -> None:
        resolved = cast(
            ast.SelectQuery,
            resolve_types(
                self._select("SELECT CAST(1 AS Integer) AS number"),
                self.context,
                dialect="clickhouse",
            ),
        )
        simplified = simplify_redundant_type_operations(resolved, self.context, dialect="clickhouse")
        sql = print_prepared_ast(simplified, self.context, dialect="clickhouse")

        assert "toInt64(1) AS number" in sql

        datetime_resolved = cast(
            ast.SelectQuery,
            resolve_types(
                self._select("SELECT CAST(toDateTime('2020-01-01') AS DateTime64(3)) AS ts"),
                self.context,
                dialect="clickhouse",
            ),
        )
        datetime_simplified = cast(
            ast.SelectQuery,
            simplify_redundant_type_operations(datetime_resolved, self.context, dialect="clickhouse"),
        )
        alias = cast(ast.Alias, datetime_simplified.select[0])

        assert isinstance(alias.expr, ast.TypeCast)
