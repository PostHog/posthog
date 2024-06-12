from posthog.hogql.ast import FloatType, IntegerType
from posthog.test.base import BaseTest
from typing import Optional
from posthog.hogql.functions.mapping import (
    compare_types,
    find_hogql_function,
    find_hogql_aggregation,
    find_hogql_posthog_function,
    HogQLFunctionMeta,
)


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
