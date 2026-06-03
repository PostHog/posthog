from unittest.mock import patch

from django.test import SimpleTestCase

from prometheus_client import REGISTRY

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


def _metric(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestHogQLTypeObservability(SimpleTestCase):
    @patch("posthog.hogql.observability.TYPE_OBSERVABILITY_SAMPLE_RATE", 0.0)
    def test_zero_sample_rate_creates_no_accumulator(self):
        base = {"engine": "current", "dialect": "clickhouse", "source": "sql_editor"}
        before = _metric("hogql_typecheck_total", {**base, "result": "success"})

        stats = create_hogql_type_observability(dialect="clickhouse", source="sql_editor")

        self.assertIsNone(stats)
        emit_hogql_type_observability(stats)  # no-op on None
        self.assertEqual(_metric("hogql_typecheck_total", {**base, "result": "success"}), before)

    @patch("posthog.hogql.observability.TYPE_OBSERVABILITY_SAMPLE_RATE", 1.0)
    def test_sampling_returns_accumulator(self):
        stats = create_hogql_type_observability(dialect="clickhouse", source="sql_editor")
        assert stats is not None
        self.assertTrue(stats.sampled)

    def test_observability_failures_never_propagate(self):
        # A bug anywhere in the observability path must not break query execution.
        stats = HogQLTypeObservability(enabled=True, sampled=True, dialect="clickhouse", source="sql_editor")
        before_errors = _metric("hogql_type_observability_errors_total", {"stage": "collect_hogql_type_coverage"})

        with patch("posthog.hogql.observability.TypeCoverageCollector", side_effect=RuntimeError("boom")):
            # Does not raise, despite the collector blowing up.
            collect_hogql_type_coverage(ast.Constant(value=1), stats)

        self.assertEqual(
            _metric("hogql_type_observability_errors_total", {"stage": "collect_hogql_type_coverage"}) - before_errors,
            1,
        )

    def test_record_methods_swallow_bad_input(self):
        stats = HogQLTypeObservability(enabled=True, sampled=True, dialect="clickhouse", source="sql_editor")
        before_errors = _metric("hogql_type_observability_errors_total", {"stage": "record_function_call"})

        # function_name=None makes classify_function_group raise (None.lower()); @_safe must swallow it.
        stats.record_function_call(function_name=None, return_type=ast.UnknownType(), signatures_present=False)  # type: ignore[arg-type]

        self.assertEqual(
            _metric("hogql_type_observability_errors_total", {"stage": "record_function_call"}) - before_errors, 1
        )
        emit_hogql_type_observability(stats)  # must not raise

    @patch("posthog.hogql.observability.TYPE_OBSERVABILITY_SAMPLE_RATE", 1.0)
    def test_emits_expression_coverage_metrics_with_bounded_labels(self):
        base = {"engine": "current", "dialect": "clickhouse", "source": "sql_editor"}
        before_observed = _metric("hogql_expression_observed_total", base)
        before_precise = _metric("hogql_expression_typed_total", {**base, "precision": "precise"})
        before_unknown = _metric("hogql_expression_typed_total", {**base, "precision": "unknown"})

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

        self.assertEqual(_metric("hogql_expression_observed_total", base) - before_observed, 3)
        self.assertEqual(_metric("hogql_expression_typed_total", {**base, "precision": "precise"}) - before_precise, 1)
        self.assertEqual(_metric("hogql_expression_typed_total", {**base, "precision": "unknown"}) - before_unknown, 2)

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
