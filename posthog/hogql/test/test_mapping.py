from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest

from posthog.hogql.ast import DateType, FloatType, IntegerType
from posthog.hogql.base import UnknownType
from posthog.hogql.context import HogQLContext
from posthog.hogql.functions.aggregations import generate_combinator_suffix_combinations
from posthog.hogql.functions.core import HogQLFunctionMeta, compare_types
from posthog.hogql.functions.mapping import (
    HOGQL_CLICKHOUSE_FUNCTIONS,
    find_hogql_aggregation,
    find_hogql_function,
    find_hogql_posthog_function,
)
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query


@pytest.mark.usefixtures("unittest_snapshot")
class TestMappings(BaseTest):
    snapshot: Any

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
        assert self._get_hogql_function("toString").clickhouse_name == "toString"
        assert find_hogql_function("TOString") == None
        assert find_hogql_function("PlUs") == None

        assert self._get_hogql_aggregation("countIf").clickhouse_name == "countIf"
        assert find_hogql_aggregation("COUNTIF") == None

        assert self._get_hogql_posthog_function("sparkline").clickhouse_name == "sparkline"
        assert find_hogql_posthog_function("SPARKLINE") == None

    def test_find_case_insensitive_function(self):
        assert self._get_hogql_function("CoAlesce").clickhouse_name == "coalesce"

        assert self._get_hogql_aggregation("SuM").clickhouse_name == "sum"

    def test_find_non_existent_function(self):
        assert find_hogql_function("functionThatDoesntExist") == None
        assert find_hogql_aggregation("functionThatDoesntExist") == None
        assert find_hogql_posthog_function("functionThatDoesntExist") == None

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
        sql, _ = prepare_and_print_ast(
            parse_expr("overloadedFunction(dateEmittingFunction('123123'))"),
            HogQLContext(self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        assert "overloadSuccess" in sql

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
                    toStartOfInterval(toDateTime('2023-01-01 13:45:32'), toIntervalHour(1)) as to_start_of_interval_result,
                    toStartOfInterval(toDateTime('2023-01-01 13:45:32'), toIntervalHour(1), toDateTime('2023-01-01 13:15:00')) as to_start_of_interval_origin_result,
                    date_bin(toIntervalHour(1), toDateTime('2023-01-01 13:45:32'), toDateTime('2023-01-01 13:15:00')) as date_bin_result,
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
        assert result_dict["truncated_hour"] == datetime(2023, 1, 1, 13, 0, tzinfo=UTC)
        assert result_dict["truncated_day"] == datetime(2023, 1, 1, 0, 0, tzinfo=UTC)
        assert result_dict["truncated_month"] == date(2023, 1, 1)
        assert result_dict["truncated_quarter"] == date(2023, 1, 1)
        assert result_dict["truncated_year"] == date(2023, 1, 1)
        assert result_dict["interval_result"] == datetime(2024, 3, 4, 4, 5, 6, tzinfo=UTC)
        assert result_dict["timestamp_result"] == datetime(2023, 1, 1, 12, 34, 56, tzinfo=UTC)
        assert result_dict["timestamptz_result"] == datetime(2023, 1, 1, 12, 34, 56, tzinfo=UTC)
        assert result_dict["timezone_result"] == datetime(2023, 1, 1, 13, 45, 32, tzinfo=UTC)
        assert result_dict["to_start_of_interval_result"] == datetime(2023, 1, 1, 13, 0, tzinfo=UTC)
        assert result_dict["to_start_of_interval_origin_result"] == datetime(2023, 1, 1, 13, 15, tzinfo=UTC)
        assert result_dict["date_bin_result"] == datetime(2023, 1, 1, 13, 15, tzinfo=UTC)
        assert result_dict["date_part_year"] == 2023
        assert result_dict["date_part_month"] == 1
        assert result_dict["date_part_day"] == 1
        assert result_dict["date_part_hour"] == 13
        assert result_dict["to_timestamp_result"] == datetime(2023, 1, 1, 13, 25, 32)
        assert result_dict["to_char_result"] == "2023-01-01"
        assert result_dict["make_date_result"] == date(2023, 1, 1)
        assert result_dict["date_add_result"] == datetime(2023, 1, 1, 14, 45, 32, tzinfo=UTC)
        assert result_dict["date_sub_result"] == datetime(2023, 1, 1, 12, 45, 32, tzinfo=UTC)
        assert result_dict["date_diff_result"] == 1
        assert result_dict["to_date_result"] == date(2023, 1, 1)

        # String function assertions
        assert result_dict["ascii_result"] == 65
        assert result_dict["repeat_result"] == "pgpgpg"
        assert result_dict["initcap_result"] == "Hello World"
        assert result_dict["left_result"] == "he"
        assert result_dict["right_result"] == "lo"
        assert result_dict["lpad_result"] == "xyxhi"
        assert result_dict["rpad_result"] == "hixyx"
        assert result_dict["ltrim_result"] == "hello  "
        assert result_dict["rtrim_result"] == "  hello"
        assert result_dict["btrim_result"] == "hello"
        assert result_dict["split_part_result"] == "def"

        # Window function assertions
        assert result_dict["lag_result"] is None  # First row has no lag
        assert result_dict["lead_result"] == 2  # First row leads to 2
        assert result_dict["lag_2_result"] is None  # First row has no lag 2
        assert result_dict["lead_2_result"] == 3  # First row leads 2 to 3
        assert result_dict["lag_default_result"] == 9  # First row lag with default
        assert result_dict["lead_default_result"] == 2  # First row lead with default

        # Aggregate function assertions
        assert result_dict["array_agg_result"] == [1, 2, 3, 4, 5]
        assert result_dict["json_agg_result"] == "[1,2,3,4,5]"
        assert result_dict["string_agg_result"] == "1,2,3,4,5"
        assert result_dict["every_result"]  # All values > 0

        # Aggregate function assertions for NULL values
        assert result_dict["array_agg_null_result"] == None
        assert result_dict["json_agg_null_result"] == None
        assert result_dict["string_agg_null_result"] == None
        assert not result_dict["every_null_result"]  # No values > 0

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

        assert result_dict["empty_map"] == {}
        assert result_dict["single_pair_map"] == {"key1": "value1"}
        assert result_dict["two_pair_map"] == {"key1": "value1", "key2": "value2"}
        assert result_dict["multi_pair_map"] == {"a": "2023-01-01", "b": "100", "c": "50", "d": "50"}

    def test_language_code_to_name_function(self):
        """Test the languageCodeToName function that maps language codes to full language names."""
        response = execute_hogql_query(
            """
            SELECT
                languageCodeToName('en') as english_name,
                languageCodeToName('es') as spanish_name,
                languageCodeToName('invalid') as invalid_code,
                languageCodeToName(NULL) as null_code
            """,
            self.team,
        )

        if response.columns is None:
            raise ValueError("Query returned no columns")
        result_dict = dict(zip(response.columns, response.results[0]))

        assert result_dict["english_name"] == "English"
        assert result_dict["spanish_name"] == "Spanish"
        assert result_dict["invalid_code"] == "Unknown"
        assert result_dict["null_code"] == "Unknown"

    def test_isValidJSON_function(self):
        """Test that isValidJSON translates correctly from HogQL to ClickHouse."""
        response = execute_hogql_query(
            """
            SELECT
                isValidJSON('{"valid": true}') as valid_json,
                isValidJSON('invalid json') as invalid_json
            """,
            self.team,
        )

        if response.columns is None:
            raise ValueError("Query returned no columns")
        result_dict = dict(zip(response.columns, response.results[0]))

        # Verify HogQL to ClickHouse translation works correctly
        assert result_dict["valid_json"] == 1
        assert result_dict["invalid_json"] == 0

    def test_JSONHas_function(self):
        """Test that JSONHas translates correctly from HogQL to ClickHouse."""
        response = execute_hogql_query(
            """
            SELECT
                JSONHas('{"a": "hello", "b": [-100, 200.0, 300]}', 'b') as has_key,
                JSONHas('{"a": "hello", "b": [-100, 200.0, 300]}', 'nonexistent') as missing_key
            """,
            self.team,
        )

        if response.columns is None:
            raise ValueError("Query returned no columns")
        result_dict = dict(zip(response.columns, response.results[0]))

        # Verify HogQL to ClickHouse translation works correctly
        assert result_dict["has_key"] == 1
        assert result_dict["missing_key"] == 0

    def test_json_functions_basic(self):
        """Test basic JSON functions translate correctly from HogQL to ClickHouse."""
        response = execute_hogql_query(
            """
            SELECT
                JSONLength('{"a": [1, 2, 3], "b": {"c": "hello"}}') as obj_length,
                JSONArrayLength('[1, 2, 3, 4, 5]') as array_length,
                JSONType('{"key": "value"}', 'key') as string_type,
                JSONExtract('{"num": 42}', 'num', 'Int32') as extracted_int
            """,
            self.team,
        )

        if response.columns is None:
            raise ValueError("Query returned no columns")
        result_dict = dict(zip(response.columns, response.results[0]))

        # Verify basic functionality
        assert result_dict["obj_length"] == 2  # 2 keys in object
        assert result_dict["array_length"] == 5  # 5 elements in array
        assert result_dict["string_type"] == "String"  # type of "value"
        assert result_dict["extracted_int"] == 42  # extracted integer

    def test_generated_aggregate_combinator_functions_snapshot(self):
        generated_sigs = [
            f"{name}: ({sig.min_args}, {sig.max_args})"
            for (name, sig) in generate_combinator_suffix_combinations().items()
        ]

        assert generated_sigs == self.snapshot
