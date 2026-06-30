from datetime import date
from typing import Optional, cast

import pytest

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import FloatArrayDatabaseField
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.resolver import resolve_types
from posthog.hogql.transforms.type_aware_simplification import simplify_redundant_type_operations
from posthog.hogql.type_diagnostics import (
    build_select_expression_type_name_query,
    compare_select_expression_types_with_type_names,
    function_catalog_inventory,
    resolve_with_type_diagnostics,
)
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
        assert least_common_supertype(
            [ast.BooleanType(nullable=False), ast.BooleanType(nullable=True)]
        ) == ast.BooleanType(nullable=True)

    def test_least_common_supertype_map_tuple_and_unknown_helpers(self) -> None:
        # Maps unify their value types and propagate nullability across branches.
        assert least_common_supertype(
            [
                ast.MapType(
                    key_type=ast.StringType(nullable=False),
                    value_type=ast.IntegerType(nullable=False),
                    nullable=False,
                ),
                ast.MapType(
                    key_type=ast.StringType(nullable=False),
                    value_type=ast.FloatType(nullable=False),
                    nullable=True,
                ),
            ]
        ) == ast.MapType(
            key_type=ast.StringType(nullable=False),
            value_type=ast.FloatType(nullable=False),
            nullable=True,
        )

        # Tuples keep field names only when every branch agrees on them.
        assert least_common_supertype(
            [
                ast.TupleType(item_types=[ast.IntegerType(nullable=False)], field_names=["a"], nullable=False),
                ast.TupleType(item_types=[ast.FloatType(nullable=False)], field_names=["a"], nullable=False),
            ]
        ) == ast.TupleType(item_types=[ast.FloatType(nullable=False)], field_names=["a"], nullable=False)
        assert least_common_supertype(
            [
                ast.TupleType(item_types=[ast.IntegerType(nullable=False)], field_names=["a"], nullable=False),
                ast.TupleType(item_types=[ast.FloatType(nullable=False)], field_names=["b"], nullable=False),
            ]
        ) == ast.TupleType(item_types=[ast.FloatType(nullable=False)], field_names=[], nullable=False)

        # No known branches collapses to UnknownType (empty input, or all-unknown input).
        assert least_common_supertype([]) == ast.UnknownType()
        assert least_common_supertype([ast.UnknownType(), ast.UnknownType()]) == ast.UnknownType()
        # A vacuous unknown branch (null literal / empty container) is absorbed: the known type
        # wins, only contributing nullability.
        assert least_common_supertype([ast.UnknownType(), ast.IntegerType(nullable=False)]) == ast.IntegerType(
            nullable=True
        )

    def test_unanalyzable_unknown_poisons_supertype(self) -> None:
        # An unanalyzable unknown (e.g. an unmapped function) could be any type, so it poisons the
        # supertype instead of being absorbed by a known sibling.
        assert least_common_supertype(
            [ast.UnknownType(unanalyzable=True), ast.IntegerType(nullable=False)]
        ) == ast.UnknownType(unanalyzable=True)
        # Poisoning still propagates nullability and survives across a mix of known branches.
        assert least_common_supertype(
            [ast.UnknownType(unanalyzable=True), ast.StringType(nullable=False), ast.IntegerType(nullable=True)]
        ) == ast.UnknownType(unanalyzable=True)
        # A vacuous unknown does not poison even alongside an unanalyzable-free set.
        assert least_common_supertype([ast.UnknownType(), ast.UnknownType(unanalyzable=True)]) == ast.UnknownType(
            unanalyzable=True
        )

    def test_resolver_poisons_only_unanalyzable_branches(self) -> None:
        # An unmapped function (throwIf) infers as unanalyzable, poisoning the unifying call's type...
        for query in ("SELECT ifNull(throwIf(0, 'x'), 1)", "SELECT if(1, throwIf(0, 'x'), 1)"):
            node = cast(ast.SelectQuery, resolve_types(self._select(query), self.context, dialect="clickhouse"))
            column_type = node.select[0].type
            assert column_type is not None
            assert column_type.resolve_constant_type(self.context) == ast.UnknownType(unanalyzable=True), query

        # ...but a null literal is a known-vacuous branch, so the known arm still wins (the null
        # branch only contributes nullability).
        self._assert_first_column_type("SELECT ifNull(NULL, 1)", ast.IntegerType(nullable=True))
        # ...and an empty array imposes no constraint, so concat keeps the known element type.
        self._assert_first_column_type(
            "SELECT arrayConcat([], [1, 2])", ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=True))
        )

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
        # toBool renders as accurateCastOrNull, so it can be NULL on parse failure even for non-null input
        self._assert_first_column_type("SELECT toBool(event) FROM events", ast.BooleanType(nullable=True))
        self._assert_first_column_type("SELECT reinterpretAsUInt64('12345678')", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT reinterpretAsFloat64('12345678')", ast.FloatType(nullable=False))
        self._assert_first_column_type("SELECT reinterpretAsUUID('1234567890123456')", ast.UUIDType(nullable=False))

    def test_resolver_infers_date_arithmetic_granularity(self) -> None:
        # Sub-day arithmetic promotes a Date to DateTime, matching ClickHouse.
        for sub_day in ("addHours", "addMinutes", "addSeconds", "subtractHours", "subtractMinutes"):
            self._assert_first_column_type(
                f"SELECT {sub_day}(toDate('2020-01-01'), 1)", ast.DateTimeType(nullable=False)
            )

        # Day-and-above arithmetic keeps the Date.
        for day_plus in ("addDays", "addWeeks", "addMonths", "subtractDays", "subtractYears"):
            self._assert_first_column_type(f"SELECT {day_plus}(toDate('2020-01-01'), 1)", ast.DateType(nullable=False))

        # A DateTime argument stays a DateTime under sub-day arithmetic.
        self._assert_first_column_type(
            "SELECT addHours(toDateTime('2020-01-01 00:00:00'), 1)", ast.DateTimeType(nullable=False)
        )

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
        self._assert_first_column_type(
            "SELECT arraySort(x -> x + 1, [1, 2])",
            ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False)),
        )
        self._assert_first_column_type(
            "SELECT arrayReverseSort(x -> x + 1, [1, 2])",
            ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False)),
        )
        self._assert_first_column_type(
            "SELECT arrayFill(x -> x > 0, [1, 2])",
            ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False)),
        )
        self._assert_first_column_type(
            "SELECT arraySplit(x -> x = 0, [1, 0, 2])",
            ast.ArrayType(
                nullable=False,
                item_type=ast.ArrayType(nullable=False, item_type=ast.IntegerType(nullable=False)),
            ),
        )
        self._assert_first_column_type(
            "SELECT arrayFold((acc, x) -> acc + x, [1, 2], 0)",
            ast.IntegerType(nullable=False),
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
        lambda_expr = lambda_node.expr
        assert isinstance(lambda_expr, ast.Expr)
        assert lambda_expr.type is not None
        assert lambda_expr.type.resolve_constant_type(self.context) == ast.FloatType(nullable=False)
        assert call.type is not None
        assert call.type.resolve_constant_type(self.context) == ast.ArrayType(
            nullable=False,
            item_type=ast.FloatType(nullable=False),
        )

    def test_resolver_binds_lambda_first_array_helper_argument_types(self) -> None:
        node = cast(
            ast.SelectQuery,
            resolve_types(
                self._select("SELECT arraySort((x, y) -> y, [1], ['b'])"),
                self.context,
                dialect="clickhouse",
            ),
        )

        call = cast(ast.Call, node.select[0])
        lambda_node = cast(ast.Lambda, call.args[0])
        lambda_type = cast(ast.SelectQueryType, lambda_node.type)
        first_arg = cast(ast.FieldAliasType, lambda_type.aliases["x"])
        second_arg = cast(ast.FieldAliasType, lambda_type.aliases["y"])

        assert first_arg.resolve_constant_type(self.context) == ast.IntegerType(nullable=False)
        assert second_arg.resolve_constant_type(self.context) == ast.StringType(nullable=False)
        assert call.type is not None
        assert call.type.resolve_constant_type(self.context) == ast.ArrayType(
            nullable=False,
            item_type=ast.IntegerType(nullable=False),
        )

    def test_resolver_binds_array_fold_accumulator_and_element_types(self) -> None:
        node = cast(
            ast.SelectQuery,
            resolve_types(
                self._select("SELECT arrayFold((acc, x) -> acc + x, [1, 2], 0)"),
                self.context,
                dialect="clickhouse",
            ),
        )

        call = cast(ast.Call, node.select[0])
        lambda_node = cast(ast.Lambda, call.args[0])
        lambda_type = cast(ast.SelectQueryType, lambda_node.type)
        accumulator_arg = cast(ast.FieldAliasType, lambda_type.aliases["acc"])
        element_arg = cast(ast.FieldAliasType, lambda_type.aliases["x"])

        assert accumulator_arg.resolve_constant_type(self.context) == ast.IntegerType(nullable=False)
        assert element_arg.resolve_constant_type(self.context) == ast.IntegerType(nullable=False)
        assert call.type is not None
        assert call.type.resolve_constant_type(self.context) == ast.IntegerType(nullable=False)

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
        self._assert_first_column_type("SELECT ifNull(1.5, 0)", ast.FloatType(nullable=False))
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

    def test_resolver_infers_string_search_function_types(self) -> None:
        # Predicates return a 0/1 flag, modeled as Boolean (consistent with like/ilike).
        self._assert_first_column_type("SELECT match('abc', 'a')", ast.BooleanType(nullable=False))
        self._assert_first_column_type("SELECT startsWith('abc', 'a')", ast.BooleanType(nullable=False))
        self._assert_first_column_type("SELECT endsWith('abc', 'c')", ast.BooleanType(nullable=False))
        self._assert_first_column_type("SELECT hasToken('a b c', 'b')", ast.BooleanType(nullable=False))
        self._assert_first_column_type("SELECT hasSubsequence('abc', 'ac')", ast.BooleanType(nullable=False))
        # Counts, positions and lengths return the integer family (UInt64/Int32).
        self._assert_first_column_type("SELECT position('abc', 'b')", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT position('abc', 'b', 1)", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT countSubstrings('aaa', 'a')", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT lengthUTF8('abc')", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT ascii('a')", ast.IntegerType(nullable=False))
        # Extractors return a String.
        self._assert_first_column_type("SELECT extract('abc', '(b)')", ast.StringType(nullable=False))
        self._assert_first_column_type("SELECT regexpExtract('abc', '(b)')", ast.StringType(nullable=False))
        # Nullability propagates from the arguments: a nullable haystack yields a nullable result.
        self._assert_first_column_type("SELECT match(properties.foo, 'a') FROM events", ast.BooleanType(nullable=True))

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

    def test_resolver_infers_more_optimizer_relevant_function_types(self) -> None:
        self._assert_first_column_type("SELECT formatReadableSize(1024)", ast.StringType(nullable=False))
        self._assert_first_column_type(
            "SELECT formatDateTime(toDateTime('2024-01-01'), '%F')",
            ast.StringType(nullable=False),
        )
        self._assert_first_column_type("SELECT toYear(toDate('2024-01-01'))", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT row_number() OVER () FROM events", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT lag(event) OVER () FROM events", ast.StringType(nullable=True))
        self._assert_first_column_type("SELECT bitmapCardinality(bitmapBuild([1, 2]))", ast.IntegerType(nullable=False))
        self._assert_first_column_type("SELECT bitmapContains(bitmapBuild([1, 2]), 1)", ast.BooleanType(nullable=False))
        self._assert_first_column_type("SELECT bitmapBuild([1, 2])", ast.UnknownType(nullable=False))
        self._assert_first_column_type(
            "SELECT mapUpdate(map('a', 1), map('b', 2.0))",
            ast.MapType(
                nullable=False,
                key_type=ast.StringType(nullable=False),
                value_type=ast.FloatType(nullable=False),
            ),
        )

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
            self._select("SELECT throwIf(0, 'not reached')"),
            self.context,
            dialect="clickhouse",
        )

        assert diagnostics.report.unknown_count == 1
        assert diagnostics.report.unknowns_by_source() == {"missing_function_signature": 1}
        assert diagnostics.report.unknowns_by_detail() == {"throwIf": 1}
        assert diagnostics.report.optimizer_blocker_count == 1
        assert diagnostics.report.optimizer_blockers_by_source() == {"missing_function_signature": 1}
        assert diagnostics.report.unknowns[0].detail == "throwIf"

    def test_type_diagnostics_reports_select_expression_types(self) -> None:
        diagnostics = resolve_with_type_diagnostics(
            self._select("SELECT 1 AS one, 'event' AS event_name, [1, 2.0] AS numbers"),
            self.context,
            dialect="clickhouse",
        )

        assert diagnostics.report.unknown_count == 0
        assert [diagnostic.alias for diagnostic in diagnostics.report.select_expressions] == [
            "one",
            "event_name",
            "numbers",
        ]

        by_alias = diagnostics.report.select_expression_types_by_alias()
        assert by_alias["one"].runtime_type.family == "integer"
        assert by_alias["one"].runtime_type.nullable is False
        assert by_alias["event_name"].runtime_type_display == "String"
        assert by_alias["numbers"].runtime_type.family == "array"
        assert by_alias["numbers"].runtime_type.item_type is not None
        assert by_alias["numbers"].runtime_type.item_type.family == "float"
        assert by_alias["one"].debug_dict()["runtime_type"] == {
            "family": "integer",
            "nullable": False,
            "dialect": "common",
            "signed": True,
            "bits": 64,
        }

    def test_type_diagnostics_builds_type_name_query_and_compares_results(self) -> None:
        query = self._select("SELECT 1 AS one, 2.5 AS score, toString('x') AS text")
        diagnostics = resolve_with_type_diagnostics(query, self.context, dialect="clickhouse")
        type_name_query = build_select_expression_type_name_query(query, self.context, dialect="clickhouse")
        resolved_type_name_query = resolve_types(type_name_query, self.context, dialect="clickhouse")
        sql = print_prepared_ast(resolved_type_name_query, self.context, dialect="clickhouse")

        assert "toTypeName(1) AS __hogql_type_1" in sql
        assert "toTypeName(2.5) AS __hogql_type_2" in sql
        assert "toTypeName(toString(" in sql
        assert "AS __hogql_type_3" in sql

        comparisons = compare_select_expression_types_with_type_names(
            diagnostics.report,
            ["UInt8", "Float64", "String"],
            dialect="clickhouse",
        )

        assert [comparison.matches for comparison in comparisons] == [True, True, True]
        assert comparisons[0].inferred_runtime_type.display() == "Int64"
        assert comparisons[0].clickhouse_runtime_type.display() == "UInt8"

        selected_type_name_query = build_select_expression_type_name_query(
            query,
            self.context,
            dialect="clickhouse",
            expression_indexes=[1],
        )
        assert len(selected_type_name_query.select) == 1
        selected_comparisons = compare_select_expression_types_with_type_names(
            diagnostics.report,
            ["Float64"],
            dialect="clickhouse",
            expression_indexes=[1],
        )
        assert selected_comparisons[0].index == 1
        assert selected_comparisons[0].matches is True

        # A family mismatch and a nullability mismatch both surface as matches=False.
        mismatched = compare_select_expression_types_with_type_names(
            diagnostics.report,
            ["String", "Nullable(Float64)", "String"],
            dialect="clickhouse",
        )
        assert [comparison.matches for comparison in mismatched] == [False, False, True]
        assert mismatched[0].family_matches is False
        assert mismatched[0].nullability_matches is True
        assert mismatched[1].family_matches is True
        assert mismatched[1].nullability_matches is False

        # The wrong number of ClickHouse type names is a hard error.
        with pytest.raises(ValueError, match="Expected 3 ClickHouse type name"):
            compare_select_expression_types_with_type_names(
                diagnostics.report,
                ["UInt8", "Float64"],
                dialect="clickhouse",
            )

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
                "coalesce(JSONExtractString('{\"name\": \"Ada\"}', 'name'), 'unknown'), "
                "formatReadableSize(1024)"
            ),
            (
                "SELECT "
                "arrayMap(x -> x + 0.5, JSONExtract('[1, 2]', 'Array(Int64)')), "
                "arrayReduce('sum', [1, 2.0]), "
                "arrayZip([1], ['a']), "
                "arraySort(x -> x + 1, [1, 2]), "
                "arrayFold((acc, x) -> acc + x, [1, 2], 0)"
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
        assert "formatReadableSize" not in inventory.functions_without_type_inference
        assert "throwIf" in inventory.functions_without_type_inference

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

    def test_type_aware_simplification_folds_safe_literal_arithmetic(self) -> None:
        resolved = cast(
            ast.SelectQuery,
            resolve_types(
                self._select("SELECT 1 + 2 * 3 AS value, 4 / 2 AS ratio, 1 / 0 AS unsafe"),
                self.context,
                dialect="clickhouse",
            ),
        )
        simplified = cast(
            ast.SelectQuery,
            simplify_redundant_type_operations(resolved, self.context, dialect="clickhouse"),
        )

        value_alias = cast(ast.Alias, simplified.select[0])
        ratio_alias = cast(ast.Alias, simplified.select[1])
        unsafe_alias = cast(ast.Alias, simplified.select[2])

        assert isinstance(value_alias.expr, ast.Constant)
        assert value_alias.expr.value == 7
        assert value_alias.expr.type == ast.IntegerType(nullable=False)
        assert isinstance(ratio_alias.expr, ast.Constant)
        assert ratio_alias.expr.value == 2.0
        assert ratio_alias.expr.type == ast.FloatType(nullable=False)
        assert isinstance(unsafe_alias.expr, ast.ArithmeticOperation)

    def test_type_aware_simplification_folds_safe_date_interval_arithmetic(self) -> None:
        resolved = cast(
            ast.SelectQuery,
            resolve_types(
                self._select(
                    "SELECT "
                    "toDate('2024-01-01') + toIntervalDay(2) AS plus_days, "
                    "toDate('2024-01-08') - toIntervalWeek(1) AS minus_week, "
                    "toDate('2024-01-31') + toIntervalMonth(1) AS unsafe_month"
                ),
                self.context,
                dialect="clickhouse",
            ),
        )
        simplified = cast(
            ast.SelectQuery,
            simplify_redundant_type_operations(resolved, self.context, dialect="clickhouse"),
        )

        plus_days_alias = cast(ast.Alias, simplified.select[0])
        minus_week_alias = cast(ast.Alias, simplified.select[1])
        unsafe_month_alias = cast(ast.Alias, simplified.select[2])

        assert isinstance(plus_days_alias.expr, ast.Constant)
        assert plus_days_alias.expr.value == date(2024, 1, 3)
        assert plus_days_alias.expr.type == ast.DateType(nullable=False)
        assert isinstance(minus_week_alias.expr, ast.Constant)
        assert minus_week_alias.expr.value == date(2024, 1, 1)
        assert minus_week_alias.expr.type == ast.DateType(nullable=False)
        assert isinstance(unsafe_month_alias.expr, ast.ArithmeticOperation)

    def test_type_aware_simplification_folds_safe_constant_casts_nulls_and_json_paths(self) -> None:
        resolved = cast(
            ast.SelectQuery,
            resolve_types(
                self._select(
                    "SELECT "
                    "accurateCast('42', 'Int64') AS number, "
                    "toFloat(1) AS score, "
                    "toBool('true') AS flag, "
                    "ifNull(NULL, 4) AS if_null, "
                    "ifNull(5, NULL) AS if_not_null, "
                    "coalesce(NULL, NULL, 6) AS coalesced, "
                    "JSONExtract('{\"score\": 2.5}', 'score', 'Float64') AS json_score, "
                    "JSONHas('{\"score\": 2.5}', 'score') AS json_has, "
                    "JSONExtractRaw('{\"props\": {\"a\": 1}}', 'props') AS json_raw"
                ),
                self.context,
                dialect="clickhouse",
            ),
        )
        simplified = cast(
            ast.SelectQuery,
            simplify_redundant_type_operations(resolved, self.context, dialect="clickhouse"),
        )

        values = [cast(ast.Constant, cast(ast.Alias, select_expr).expr).value for select_expr in simplified.select]
        assert values == [42, 1.0, True, 4, 5, 6, 2.5, 1, '{"a":1}']

        types: list[ast.ConstantType] = []
        for select_expr in simplified.select:
            expr = cast(ast.Alias, select_expr).expr
            assert expr.type is not None
            types.append(expr.type.resolve_constant_type(self.context))

        assert types == [
            ast.IntegerType(nullable=False),
            ast.FloatType(nullable=False),
            ast.BooleanType(nullable=False),
            ast.IntegerType(nullable=False),
            ast.IntegerType(nullable=False),
            ast.IntegerType(nullable=False),
            ast.FloatType(nullable=False),
            ast.IntegerType(nullable=False),
            ast.StringType(nullable=False),
        ]

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

    def test_type_aware_simplification_leaves_unsafe_inputs_unchanged(self) -> None:
        def _simplified_expr(query: str) -> ast.Expr:
            resolved = cast(
                ast.SelectQuery,
                resolve_types(self._select(query), self.context, dialect="clickhouse"),
            )
            simplified = cast(
                ast.SelectQuery,
                simplify_redundant_type_operations(resolved, self.context, dialect="clickhouse"),
            )
            return cast(ast.Alias, simplified.select[0]).expr

        # Literal casts that cannot be evaluated stay as calls rather than folding to a constant.
        for query in (
            "SELECT accurateCast('not-a-number', 'Int64') AS x",
            "SELECT accurateCast('not-a-uuid', 'UUID') AS x",
        ):
            expr = _simplified_expr(query)
            assert isinstance(expr, ast.Call)
            assert expr.name.lower() == "accuratecast"

        # A nullable input keeps its null-fallback / null-assertion wrapper.
        if_null_expr = _simplified_expr("SELECT ifNull(nullIf(5, 3), 0) AS x")
        assert isinstance(if_null_expr, ast.Call)
        assert if_null_expr.name.lower() == "ifnull"

        assume_not_null_expr = _simplified_expr("SELECT assumeNotNull(nullIf(5, 3)) AS x")
        assert isinstance(assume_not_null_expr, ast.Call)
        assert assume_not_null_expr.name.lower() == "assumenotnull"
