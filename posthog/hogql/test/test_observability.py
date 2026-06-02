from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from posthog.hogql import ast
from posthog.hogql.observability import (
    HogQLTypeObservability,
    classify_constant_type,
    classify_expr_type,
    classify_function_group,
    collect_hogql_sql_shape,
    collect_hogql_type_coverage,
    create_hogql_type_observability,
    emit_hogql_type_observability,
)


class TestHogQLTypeObservability(SimpleTestCase):
    @override_settings(HOGQL_TYPE_OBSERVABILITY_ENABLED=False, HOGQL_TYPE_OBSERVABILITY_SAMPLE_RATE=1.0)
    @patch("posthog.hogql.observability.statsd.incr")
    def test_disabled_observability_does_not_emit_metrics(self, mock_incr):
        stats = create_hogql_type_observability(dialect="clickhouse", source="sql_editor")

        stats.expression_count = 1
        stats.typed_by_precision["precise"] = 1
        emit_hogql_type_observability(stats)

        mock_incr.assert_not_called()

    @override_settings(HOGQL_TYPE_OBSERVABILITY_ENABLED=True, HOGQL_TYPE_OBSERVABILITY_SAMPLE_RATE=1.0)
    @patch("posthog.hogql.observability.statsd.incr")
    def test_emits_expression_coverage_metrics_with_bounded_tags(self, mock_incr):
        stats = create_hogql_type_observability(dialect="clickhouse", source="sql_editor")
        node = ast.Array(
            exprs=[
                ast.Constant(value="known", type=ast.StringType()),
                ast.Call(name="unknownFunc", args=[], type=ast.UnknownType()),
            ],
            type=ast.ArrayType(item_type=ast.UnknownType()),
        )

        collect_hogql_type_coverage(node, stats)
        emit_hogql_type_observability(stats)

        mock_incr.assert_any_call(
            "hogql_expression_observed_total",
            count=3,
            tags={"engine": "current", "dialect": "clickhouse", "source": "sql_editor"},
        )
        mock_incr.assert_any_call(
            "hogql_expression_typed_total",
            count=1,
            tags={
                "engine": "current",
                "dialect": "clickhouse",
                "source": "sql_editor",
                "precision": "precise",
            },
        )
        mock_incr.assert_any_call(
            "hogql_expression_typed_total",
            count=2,
            tags={
                "engine": "current",
                "dialect": "clickhouse",
                "source": "sql_editor",
                "precision": "unknown",
            },
        )

    def test_classifies_type_precision(self):
        self.assertEqual(classify_constant_type(ast.StringType()), "precise")
        self.assertEqual(classify_constant_type(ast.UnknownType()), "unknown")
        self.assertEqual(classify_constant_type(ast.ArrayType(item_type=ast.UnknownType())), "unknown")
        self.assertEqual(
            classify_expr_type(ast.CallType(name="concat", arg_types=[ast.StringType()], return_type=ast.StringType())),
            "precise",
        )

    def test_collects_sql_shape_pathologies_from_ast(self):
        stats = HogQLTypeObservability(enabled=True, sampled=True, dialect="clickhouse", source="sql_editor")
        node = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toDateTime", args=[ast.Field(chain=["timestamp"])]),
                ast.Constant(value="fallback"),
            ],
        )

        collect_hogql_sql_shape(node, stats)

        self.assertEqual(stats.sql_shape["nullable_comparison_wrapper"], 1)
        self.assertEqual(stats.sql_shape["datetime_cast"], 1)
        self.assertEqual(stats.sql_shape["property_conversion_wrapper"], 1)

    def test_records_property_typing_results(self):
        stats = HogQLTypeObservability(enabled=True, sampled=True, dialect="clickhouse", source="sql_editor")

        stats.record_property_definition_lookup(property_source="event", known_count=2, total_count=3)
        stats.record_property_definition_lookup(property_source="person", known_count=1, total_count=1)

        self.assertEqual(stats.property_access_count, 4)
        self.assertEqual(stats.property_typing["event_known"], 2)
        self.assertEqual(stats.property_typing["event_unknown"], 1)
        self.assertEqual(stats.property_typing["person_known"], 1)
        self.assertEqual(stats.unknown_by_reason["unknown_property_metadata"], 1)

    def test_function_groups_are_bounded(self):
        self.assertEqual(classify_function_group("toDateTime"), "cast")
        self.assertEqual(classify_function_group("JSONExtractString"), "json")
        self.assertEqual(classify_function_group("arrayMap"), "array")
        self.assertEqual(classify_function_group("someCustomThing"), "unknown")
