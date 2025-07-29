from posthog.hogql.ast import FloatType, IntegerType, DateType
from posthog.hogql.base import UnknownType
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer import print_ast
from posthog.test.base import BaseTest
from typing import Optional
from posthog.hogql.functions.mapping import (
    compare_types,
    find_hogql_function,
    find_hogql_aggregation,
    find_hogql_posthog_function,
    HogQLFunctionMeta,
    HOGQL_CLICKHOUSE_FUNCTIONS,
)
from datetime import datetime, UTC
from freezegun import freeze_time
from posthog.hogql.query import execute_hogql_query
from datetime import date


class TestMappings(BaseTest):
    def _return_present_function(self, function: Optional[HogQLFunctionMeta]) -> HogQLFunctionMeta:
        assert function is not None
        return function

    def _get_hogql_function(self, name: str) -> HogQLFunctionMeta:
        return self._return_present_function(find_hogql_function(name))

    def _get_hogql_aggregation(self, name: str) -> HogQLFunctionMeta:
        return self._return_present_function(find_hogql_aggregation(name))

    def _get_hogql_posthog_function(self, name: str) -> HogQLFunctionMeta:
        return self._return_present_function(find_hogql_posthog_function(name))

    def test_find_case_sensitive_function(self):
        self.assertEqual(self._get_hogql_function("toString").clickhouse_name, "toString")
        self.assertEqual(find_hogql_function("TOString"), None)
        self.assertEqual(find_hogql_function("PlUs"), None)

        self.assertEqual(self._get_hogql_aggregation("countIf").clickhouse_name, "countIf")
        self.assertEqual(find_hogql_aggregation("COUNTIF"), None)

        self.assertEqual(self._get_hogql_posthog_function("sparkline").clickhouse_name, "sparkline")
        self.assertEqual(find_hogql_posthog_function("SPARKLINE"), None)

    def test_find_case_insensitive_function(self):
        self.assertEqual(self._get_hogql_function("CoAlesce").clickhouse_name, "coalesce")

        self.assertEqual(self._get_hogql_aggregation("SuM").clickhouse_name, "sum")

    def test_find_non_existent_function(self):
        self.assertEqual(find_hogql_function("functionThatDoesntExist"), None)
        self.assertEqual(find_hogql_aggregation("functionThatDoesntExist"), None)
        self.assertEqual(find_hogql_posthog_function("functionThatDoesntExist"), None)

    def test_compare_types(self):
        res = compare_types([IntegerType()], (IntegerType(),))
        assert res is True

    def test_compare_types_mismatch(self):
        res = compare_types([IntegerType()], (FloatType(),))
        assert res is False

    def test_compare_types_mismatch_lengths(self):
        res = compare_types([IntegerType()], (IntegerType(), IntegerType()))
        assert res is False

    def test_compare_types_mismatch_differing_order(self):
        res = compare_types([IntegerType(), FloatType()], (FloatType(), IntegerType()))
        assert res is False

    def test_unknown_type_mapping(self):
        HOGQL_CLICKHOUSE_FUNCTIONS["overloadedFunction"] = HogQLFunctionMeta(
            "overloadFailure",
            1,
            1,
            overloads=[((DateType,), "overloadSuccess")],
        )

        HOGQL_CLICKHOUSE_FUNCTIONS["dateEmittingFunction"] = HogQLFunctionMeta(
            "dateEmittingFunction",
            1,
            1,
            signatures=[
                ((UnknownType(),), DateType()),
            ],
        )
        ast = print_ast(
            parse_expr("overloadedFunction(dateEmittingFunction('123123'))"),
            HogQLContext(self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        assert "overloadSuccess" in ast

    @freeze_time("2023-01-01T12:00:00Z")
    def test_postgres_functions(self):
        response = execute_hogql_query(
            """
            WITH
            date_functions AS (
                SELECT
                    now() as current_time,
                    date_trunc('hour', toDateTime('2023-01-01 13:45:32')) as truncated_hour,
                    date_trunc('day', toDateTime('2023-01-01 13:45:32')) as truncated_day,
                    date_trunc('month', toDateTime('2023-01-01 13:45:32')) as truncated_month,
                    date_trunc('quarter', toDateTime('2023-01-01 13:45:32')) as truncated_quarter,
                    date_trunc('year', toDateTime('2023-01-01 13:45:32')) as truncated_year,
                    toDateTime('2023-01-01 00:00:00') + make_interval(1, 2, 3, 4, 5, 6) as interval_result,
                    make_timestamp(2023, 1, 1, 12, 34, 56) as timestamp_result,
                    make_timestamptz(2023, 1, 1, 12, 34, 56, 'UTC') as timestamptz_result,
                    timezone('UTC', toDateTime('2023-01-01 13:45:32')) as timezone_result,
                    toYear(toDateTime('2023-01-01 13:45:32')) as date_part_year,
                    toMonth(toDateTime('2023-01-01 13:45:32')) as date_part_month,
                    toDayOfMonth(toDateTime('2023-01-01 13:45:32')) as date_part_day,
                    toHour(toDateTime('2023-01-01 13:45:32')) as date_part_hour,
                    to_timestamp(1672579532) as to_timestamp_result,
                    to_char(toDateTime('2023-01-01 13:45:32'), '%Y-%m-%d') as to_char_result,
                    make_date(2023, 1, 1) as make_date_result,
                    current_timestamp() as current_timestamp_result,
                    current_date() as current_date_result,
                    date_add(toDateTime('2023-01-01 13:45:32'), toIntervalHour(1)) as date_add_result,
                    date_subtract(toDateTime('2023-01-01 13:45:32'), toIntervalHour(1)) as date_sub_result,
                    date_diff('hour', toDateTime('2023-01-01 13:45:32'), toDateTime('2023-01-01 14:45:32')) as date_diff_result,
                    to_date('2023-01-01') as to_date_result
            ),
            string_functions AS (
                SELECT
                    ascii('A') as ascii_result,
                    repeat('pg', 3) as repeat_result,
                    initcap('hello world') as initcap_result,
                    left('hello', 2) as left_result,
                    right('hello', 2) as right_result,
                    lpad('hi', 5, 'xy') as lpad_result,
                    rpad('hi', 5, 'xy') as rpad_result,
                    ltrim('  hello  ') as ltrim_result,
                    rtrim('  hello  ') as rtrim_result,
                    btrim('  hello  ') as btrim_result,
                    split_part('abc.def.ghi', '.', 2) as split_part_result
            ),
            window_functions AS (
                SELECT
                    value,
                    lag(value) OVER (ORDER BY value) as lag_result,
                    lead(value) OVER (ORDER BY value) as lead_result,
                    lag(value, 2) OVER (ORDER BY value) as lag_2_result,
                    lead(value, 2) OVER (ORDER BY value) as lead_2_result,
                    lag(value, 1, 9) OVER (ORDER BY value) as lag_default_result,
                    lead(value, 1, 9) OVER (ORDER BY value) as lead_default_result
                FROM
                    (SELECT arrayJoin([1,2,3,4,5]) as value)
            ),
            aggregate_functions AS (
                SELECT
                    array_agg(value) as array_agg_result,
                    json_agg(value) as json_agg_result,
                    string_agg(toString(value), ',') as string_agg_result,
                    every(value > 0) as every_result
                FROM
                    (SELECT arrayJoin([1,2,3,4,5]) as value)
            ),
            aggregate_functions_null as (
                SELECT
                    array_agg(value) as array_agg_null_result,
                    json_agg(value) as json_agg_null_result,
                    string_agg(toString(value), ',') as string_agg_null_result,
                    every(value > 0) as every_null_result
                FROM
                    (SELECT arrayJoin([NULL]) as value)
            )
            SELECT
                date_functions.*,
                string_functions.*,
                window_functions.*,
                aggregate_functions.*,
                aggregate_functions_null.*
            FROM
                date_functions,
                string_functions,
                window_functions,
                aggregate_functions,
                aggregate_functions_null
            """,
            self.team,
        )

        # Convert results to a dictionary for easier assertions
        if response.columns is None:
            raise ValueError("Query returned no columns")
        result_dict = dict(zip(response.columns, response.results[0]))

        # Date function assertions
        self.assertEqual(result_dict["truncated_hour"], datetime(2023, 1, 1, 13, 0, tzinfo=UTC))
        self.assertEqual(result_dict["truncated_day"], datetime(2023, 1, 1, 0, 0, tzinfo=UTC))
        self.assertEqual(result_dict["truncated_month"], date(2023, 1, 1))
        self.assertEqual(result_dict["truncated_quarter"], date(2023, 1, 1))
        self.assertEqual(result_dict["truncated_year"], date(2023, 1, 1))
        self.assertEqual(result_dict["interval_result"], datetime(2024, 3, 4, 4, 5, 6, tzinfo=UTC))
        self.assertEqual(result_dict["timestamp_result"], datetime(2023, 1, 1, 12, 34, 56, tzinfo=UTC))
        self.assertEqual(result_dict["timestamptz_result"], datetime(2023, 1, 1, 12, 34, 56, tzinfo=UTC))
        self.assertEqual(result_dict["timezone_result"], datetime(2023, 1, 1, 13, 45, 32, tzinfo=UTC))
        self.assertEqual(result_dict["date_part_year"], 2023)
        self.assertEqual(result_dict["date_part_month"], 1)
        self.assertEqual(result_dict["date_part_day"], 1)
        self.assertEqual(result_dict["date_part_hour"], 13)
        self.assertEqual(result_dict["to_timestamp_result"], datetime(2023, 1, 1, 13, 25, 32))
        self.assertEqual(result_dict["to_char_result"], "2023-01-01")
        self.assertEqual(result_dict["make_date_result"], date(2023, 1, 1))
        self.assertEqual(result_dict["date_add_result"], datetime(2023, 1, 1, 14, 45, 32, tzinfo=UTC))
        self.assertEqual(result_dict["date_sub_result"], datetime(2023, 1, 1, 12, 45, 32, tzinfo=UTC))
        self.assertEqual(result_dict["date_diff_result"], 1)
        self.assertEqual(result_dict["to_date_result"], date(2023, 1, 1))

        # String function assertions
        self.assertEqual(result_dict["ascii_result"], 65)
        self.assertEqual(result_dict["repeat_result"], "pgpgpg")
        self.assertEqual(result_dict["initcap_result"], "Hello World")
        self.assertEqual(result_dict["left_result"], "he")
        self.assertEqual(result_dict["right_result"], "lo")
        self.assertEqual(result_dict["lpad_result"], "xyxhi")
        self.assertEqual(result_dict["rpad_result"], "hixyx")
        self.assertEqual(result_dict["ltrim_result"], "hello  ")
        self.assertEqual(result_dict["rtrim_result"], "  hello")
        self.assertEqual(result_dict["btrim_result"], "hello")
        self.assertEqual(result_dict["split_part_result"], "def")

        # Window function assertions
        self.assertIsNone(result_dict["lag_result"])  # First row has no lag
        self.assertEqual(result_dict["lead_result"], 2)  # First row leads to 2
        self.assertIsNone(result_dict["lag_2_result"])  # First row has no lag 2
        self.assertEqual(result_dict["lead_2_result"], 3)  # First row leads 2 to 3
        self.assertEqual(result_dict["lag_default_result"], 9)  # First row lag with default
        self.assertEqual(result_dict["lead_default_result"], 2)  # First row lead with default

        # Aggregate function assertions
        self.assertEqual(result_dict["array_agg_result"], [1, 2, 3, 4, 5])
        self.assertEqual(result_dict["json_agg_result"], "[1,2,3,4,5]")
        self.assertEqual(result_dict["string_agg_result"], "1,2,3,4,5")
        self.assertTrue(result_dict["every_result"])  # All values > 0

        # Aggregate function assertions for NULL values
        self.assertEqual(result_dict["array_agg_null_result"], None)
        self.assertEqual(result_dict["json_agg_null_result"], None)
        self.assertEqual(result_dict["string_agg_null_result"], None)
        self.assertFalse(result_dict["every_null_result"])  # No values > 0

    def test_function_mapping(self):
        response = execute_hogql_query(
            """
            SELECT
                toFloat(3.14),
                toFloat(NULL),
                toFloatOrDefault(3, 7.),
                toFloatOrDefault(3.14, 7.),
                toFloatOrZero('3.14'),
                toFloatOrDefault('3.14', 7.),
                toFloatOrZero(''),
                toFloatOrDefault('', 7.),
                toFloatOrZero('bla'),
                toFloatOrDefault('bla', 7.),
                toFloatOrZero(NULL),
                toFloatOrDefault(NULL, 7.)
        """,
            self.team,
        )
        assert response.columns is not None
        assert response.results[0] == (3.14, None, 3.0, 3.14, 3.14, 3.14, 0.0, 7.0, 0.0, 7.0, None, 7.0)

    def test_map_function_with_multiple_key_value_pairs(self):
        """Test that the map function accepts multiple key-value pairs."""
        response = execute_hogql_query(
            """
            SELECT
                map() as empty_map,
                map('key1', 'value1') as single_pair_map,
                map('key1', 'value1', 'key2', 'value2') as two_pair_map,
                map(
                    'a', toString('2023-01-01'),
                    'b', toString(100),
                    'c', toString(50),
                    'd', toString(50)
                ) as multi_pair_map
            """,
            self.team,
        )

        if response.columns is None:
            raise ValueError("Query returned no columns")
        result_dict = dict(zip(response.columns, response.results[0]))

        self.assertEqual(result_dict["empty_map"], {})
        self.assertEqual(result_dict["single_pair_map"], {"key1": "value1"})
        self.assertEqual(result_dict["two_pair_map"], {"key1": "value1", "key2": "value2"})
        self.assertEqual(
            result_dict["multi_pair_map"],
            {
                "a": "2023-01-01",
                "b": "100",
                "c": "50",
                "d": "50",
            },
        )
