from typing import cast

import pytest

from posthog.schema import (
    Breakdown,
    BreakdownFilter,
    EventsNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    ExperimentStatsBase,
    ExperimentStatsValidationFailure,
    FunnelConversionWindowTimeUnit,
    StartHandling,
)

from posthog.hogql_queries.experiments.utils import (
    aggregate_variants_across_breakdowns,
    get_variant_result,
    get_variant_results,
    validate_variant_result,
)


class TestGetVariantResult:
    """Tests for get_variant_result() which parses query result tuples into structured variant results."""

    # Helper to create metrics for testing
    @staticmethod
    def create_mean_metric():
        return ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
        )

    @staticmethod
    def create_funnel_metric():
        return ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview", name="$pageview"),
                EventsNode(event="purchase", name="purchase"),
            ],
        )

    @staticmethod
    def create_ratio_metric():
        return ExperimentRatioMetric(
            numerator=EventsNode(event="purchase"),
            denominator=EventsNode(event="$pageview"),
        )

    # Mean Metric Tests
    def test_mean_metric_without_breakdown(self):
        metric = self.create_mean_metric()
        result = ("control", 100, 250.5, 750.25)

        breakdown_value, stats = get_variant_result(result, metric)

        assert breakdown_value is None
        assert stats.key == "control"
        assert stats.number_of_samples == 100
        assert stats.sum == 250.5
        assert stats.sum_squares == 750.25
        assert stats.step_counts is None
        assert stats.denominator_sum is None

    def test_mean_metric_with_breakdown(self):
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        result = ("test", "Chrome", 150, 400.0, 1200.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("Chrome",)
        assert stats.key == "test"
        assert stats.number_of_samples == 150
        assert stats.sum == 400.0
        assert stats.sum_squares == 1200.0
        assert stats.step_counts is None
        assert stats.denominator_sum is None

    # Funnel Metric Tests
    def test_funnel_metric_without_breakdown_no_sessions(self):
        metric = self.create_funnel_metric()
        result = ("control", 100, 80.0, 80.0, [100, 80])

        breakdown_value, stats = get_variant_result(result, metric)

        assert breakdown_value is None
        assert stats.key == "control"
        assert stats.number_of_samples == 100
        assert stats.sum == 80.0
        assert stats.sum_squares == 80.0
        assert stats.step_counts == [100, 80]
        assert stats.step_sessions is None
        assert stats.denominator_sum is None

    def test_funnel_metric_with_breakdown_no_sessions(self):
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview", name="$pageview"),
                EventsNode(event="purchase", name="purchase"),
            ],
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        result = ("test", "Safari", 120, 90.0, 90.0, [120, 90])

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("Safari",)
        assert stats.key == "test"
        assert stats.number_of_samples == 120
        assert stats.sum == 90.0
        assert stats.sum_squares == 90.0
        assert stats.step_counts == [120, 90]
        assert stats.step_sessions is None

    def test_funnel_metric_with_sessions(self):
        metric = self.create_funnel_metric()
        # With step_sessions data
        sessions_data = [
            [
                ("user1", "session1", "uuid1", "2024-01-01T00:00:00Z"),
                ("user2", "session2", "uuid2", "2024-01-01T00:00:01Z"),
            ],  # Step 0 sessions
            [("user1", "session1", "uuid3", "2024-01-01T00:00:02Z")],  # Step 1 sessions
        ]
        result = ("control", 100, 80.0, 80.0, [100, 80], sessions_data)

        breakdown_value, stats = get_variant_result(result, metric)

        assert breakdown_value is None
        assert stats.key == "control"
        assert stats.step_counts == [100, 80]
        assert stats.step_sessions is not None
        assert len(stats.step_sessions) == 2
        assert len(stats.step_sessions[0]) == 2  # First step has 2 sessions
        assert len(stats.step_sessions[1]) == 1  # Second step has 1 session
        assert stats.step_sessions[0][0].person_id == "user1"
        assert stats.step_sessions[0][0].session_id == "session1"
        assert stats.step_sessions[0][0].event_uuid == "uuid1"

    # Ratio Metric Tests
    def test_ratio_metric_without_breakdown(self):
        metric = self.create_ratio_metric()
        result = ("control", 100, 50.0, 75.0, 200.0, 500.0, 120.0)

        breakdown_value, stats = get_variant_result(result, metric)

        assert breakdown_value is None
        assert stats.key == "control"
        assert stats.number_of_samples == 100
        assert stats.sum == 50.0  # numerator sum
        assert stats.sum_squares == 75.0  # numerator sum_squares
        assert stats.denominator_sum == 200.0
        assert stats.denominator_sum_squares == 500.0
        assert stats.numerator_denominator_sum_product == 120.0
        assert stats.step_counts is None

    def test_ratio_metric_with_breakdown(self):
        metric = ExperimentRatioMetric(
            numerator=EventsNode(event="purchase"),
            denominator=EventsNode(event="$pageview"),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        result = ("test", "Firefox", 150, 75.0, 120.0, 300.0, 800.0, 200.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("Firefox",)
        assert stats.key == "test"
        assert stats.number_of_samples == 150
        assert stats.sum == 75.0
        assert stats.sum_squares == 120.0
        assert stats.denominator_sum == 300.0
        assert stats.denominator_sum_squares == 800.0
        assert stats.numerator_denominator_sum_product == 200.0

    # Edge Cases
    def test_breakdown_detection_numeric_second_field(self):
        """When second field is numeric, should NOT be treated as breakdown."""
        metric = self.create_mean_metric()
        result = ("control", 100, 250.5, 750.25)  # Second field is numeric

        breakdown_value, stats = get_variant_result(result, metric)

        assert breakdown_value is None  # Should NOT detect breakdown
        assert stats.number_of_samples == 100

    def test_breakdown_detection_string_second_field(self):
        """When breakdownFilter has breakdowns, should parse breakdown values."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        result = ("control", "Chrome", 100, 250.5, 750.25)  # Second field is breakdown value

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("Chrome",)  # Should parse breakdown
        assert stats.number_of_samples == 100

    @pytest.mark.parametrize(
        "variant_key,expected_key",
        [
            ("control", "control"),
            ("test", "test"),
            ("test-2", "test-2"),
            ("holdout-123", "holdout-123"),
        ],
    )
    def test_different_variant_keys(self, variant_key, expected_key):
        """Test that various variant key formats are preserved correctly."""
        metric = self.create_mean_metric()
        result = (variant_key, 100, 250.5, 750.25)

        breakdown_value, stats = get_variant_result(result, metric)

        assert stats.key == expected_key

    # Multiple Breakdown Tests
    def test_mean_metric_with_two_breakdowns(self):
        """Test parsing mean metric with 2 breakdowns."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$os"),
                    Breakdown(property="$browser"),
                ]
            ),
        )
        # Result: variant, os, browser, samples, sum, sum_squares
        result = ("test", "MacOS", "Chrome", 150, 400.0, 1200.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("MacOS", "Chrome")
        assert stats.key == "test"
        assert stats.number_of_samples == 150
        assert stats.sum == 400.0
        assert stats.sum_squares == 1200.0

    def test_funnel_metric_with_three_breakdowns(self):
        """Test parsing funnel metric with 3 breakdowns (max supported)."""
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview", name="$pageview"),
                EventsNode(event="purchase", name="purchase"),
            ],
            breakdownFilter=BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$os"),
                    Breakdown(property="$browser"),
                    Breakdown(property="$device_type"),
                ]
            ),
        )
        # Result: variant, os, browser, device_type, samples, sum, sum_squares, step_counts
        result = ("control", "MacOS", "Chrome", "Desktop", 100, 80.0, 80.0, [100, 80])

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("MacOS", "Chrome", "Desktop")
        assert stats.key == "control"
        assert stats.number_of_samples == 100
        assert stats.step_counts == [100, 80]

    def test_ratio_metric_with_numeric_breakdown(self):
        """Test that numeric breakdown values are converted to strings."""
        metric = ExperimentRatioMetric(
            numerator=EventsNode(event="purchase"),
            denominator=EventsNode(event="$pageview"),
            breakdownFilter=BreakdownFilter(
                breakdowns=[Breakdown(property="$screen_width")],  # Numeric property
            ),
        )
        # Result with numeric breakdown value
        result = ("test", 1920, 150, 75.0, 120.0, 300.0, 800.0, 200.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("1920",)  # Converted to string
        assert stats.number_of_samples == 150

    def test_multiple_breakdowns_with_mixed_types(self):
        """Test multiple breakdowns with mixed string/numeric values."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$os"),
                    Breakdown(property="$screen_width"),  # Numeric
                ]
            ),
        )
        # Result: variant, os (string), screen_width (numeric), samples, sum, sum_squares
        result = ("control", "MacOS", 1920, 100, 250.0, 750.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("MacOS", "1920")  # Both as strings
        assert stats.number_of_samples == 100

    def test_funnel_metric_with_breakdown_and_sessions(self):
        """Test funnel metric with breakdown and sessions combined."""
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview", name="$pageview"),
                EventsNode(event="purchase", name="purchase"),
            ],
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        sessions_data = [
            [("user1", "session1", "uuid1", "2024-01-01T00:00:00Z")],
            [("user1", "session1", "uuid2", "2024-01-01T00:00:01Z")],
        ]
        # Result: variant, breakdown, samples, sum, sum_squares, step_counts, step_sessions
        result = ("test", "Chrome", 100, 80.0, 80.0, [100, 80], sessions_data)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("Chrome",)
        assert stats.key == "test"
        assert stats.number_of_samples == 100
        assert stats.step_counts == [100, 80]
        assert stats.step_sessions is not None
        assert len(stats.step_sessions) == 2
        assert len(stats.step_sessions[0]) == 1
        assert stats.step_sessions[0][0].person_id == "user1"

    def test_funnel_metric_with_multiple_breakdowns_and_sessions(self):
        """Test funnel metric with multiple breakdowns and sessions."""
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview", name="$pageview"),
                EventsNode(event="purchase", name="purchase"),
            ],
            breakdownFilter=BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$os"),
                    Breakdown(property="$browser"),
                ]
            ),
        )
        sessions_data = [
            [
                ("user1", "session1", "uuid1", "2024-01-01T00:00:00Z"),
                ("user2", "session2", "uuid2", "2024-01-01T00:00:01Z"),
            ],
            [("user1", "session1", "uuid3", "2024-01-01T00:00:02Z")],
        ]
        # Result: variant, os, browser, samples, sum, sum_squares, step_counts, step_sessions
        result = ("control", "MacOS", "Chrome", 100, 80.0, 80.0, [100, 80], sessions_data)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("MacOS", "Chrome")
        assert stats.key == "control"
        assert stats.number_of_samples == 100
        assert stats.step_counts == [100, 80]
        assert stats.step_sessions is not None
        assert len(stats.step_sessions) == 2
        assert len(stats.step_sessions[0]) == 2
        assert len(stats.step_sessions[1]) == 1

    def test_ratio_metric_with_multiple_breakdowns(self):
        """Test ratio metric with multiple breakdowns."""
        metric = ExperimentRatioMetric(
            numerator=EventsNode(event="purchase"),
            denominator=EventsNode(event="$pageview"),
            breakdownFilter=BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$os"),
                    Breakdown(property="$browser"),
                ]
            ),
        )
        # Result: variant, os, browser, samples, num_sum, num_sum_sq, denom_sum, denom_sum_sq, product
        result = ("test", "MacOS", "Safari", 150, 75.0, 120.0, 300.0, 800.0, 200.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("MacOS", "Safari")
        assert stats.key == "test"
        assert stats.number_of_samples == 150
        assert stats.sum == 75.0
        assert stats.denominator_sum == 300.0
        assert stats.denominator_sum_squares == 800.0
        assert stats.numerator_denominator_sum_product == 200.0

    def test_breakdown_with_none_value(self):
        """Test that None breakdown values are converted to string 'None'."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        result = ("control", None, 100, 250.0, 750.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("None",)
        assert stats.number_of_samples == 100

    def test_breakdown_with_posthog_null_label(self):
        """Test that the special PostHog NULL label is preserved."""
        from posthog.hogql_queries.experiments.experiment_query_builder import BREAKDOWN_NULL_STRING_LABEL

        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        # SQL queries use coalesce() to convert NULL to this special label
        result = ("control", BREAKDOWN_NULL_STRING_LABEL, 100, 250.0, 750.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == (BREAKDOWN_NULL_STRING_LABEL,)
        assert stats.number_of_samples == 100

    def test_breakdown_with_empty_string(self):
        """Test that empty string breakdown values are preserved."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        result = ("control", "", 100, 250.0, 750.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("",)
        assert stats.number_of_samples == 100

    def test_zero_samples(self):
        """Test handling of zero samples."""
        metric = self.create_mean_metric()
        result = ("control", 0, 0.0, 0.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple is None
        assert stats.key == "control"
        assert stats.number_of_samples == 0
        assert stats.sum == 0.0
        assert stats.sum_squares == 0.0

    def test_funnel_with_empty_step_counts(self):
        """Test funnel metric with empty step counts."""
        metric = self.create_funnel_metric()
        result: tuple[str, int, float, float, list[int]] = ("control", 0, 0.0, 0.0, [])

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple is None
        assert stats.key == "control"
        assert stats.step_counts == []

    def test_breakdown_with_special_characters(self):
        """Test breakdown values with special characters."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        # Test with newlines, tabs, quotes
        result = ("control", 'Chrome\n"Mobile"', 100, 250.0, 750.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ('Chrome\n"Mobile"',)
        assert stats.number_of_samples == 100

    def test_breakdown_with_unicode(self):
        """Test breakdown values with unicode characters."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$city")]),
        )
        result = ("test", "東京", 150, 400.0, 1200.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("東京",)
        assert stats.number_of_samples == 150

    def test_empty_breakdown_list(self):
        """Test metric with breakdownFilter but empty breakdowns list."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[]),
        )
        result = ("control", 100, 250.0, 750.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple is None  # Empty list means no breakdown
        assert stats.number_of_samples == 100

    def test_ratio_metric_with_three_breakdowns(self):
        """Test ratio metric with maximum breakdowns (3)."""
        metric = ExperimentRatioMetric(
            numerator=EventsNode(event="purchase"),
            denominator=EventsNode(event="$pageview"),
            breakdownFilter=BreakdownFilter(
                breakdowns=[
                    Breakdown(property="$os"),
                    Breakdown(property="$browser"),
                    Breakdown(property="$device_type"),
                ]
            ),
        )
        # Result: variant, os, browser, device, samples, num_sum, num_sum_sq, denom_sum, denom_sum_sq, product
        result = ("test", "MacOS", "Safari", "Desktop", 150, 75.0, 120.0, 300.0, 800.0, 200.0)

        breakdown_tuple, stats = get_variant_result(result, metric)

        assert breakdown_tuple == ("MacOS", "Safari", "Desktop")
        assert stats.key == "test"
        assert stats.denominator_sum == 300.0


class TestGetVariantResults:
    """Tests for get_variant_results() wrapper which processes multiple result rows."""

    def test_multiple_results_without_breakdown(self):
        """Test processing multiple results without breakdowns."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
        )
        results = [
            ("control", 100, 250.5, 750.25),
            ("test", 150, 400.0, 1200.0),
        ]

        variant_results = get_variant_results(results, metric)

        assert len(variant_results) == 2
        assert variant_results[0][0] is None  # No breakdown
        assert variant_results[0][1].key == "control"
        assert variant_results[0][1].number_of_samples == 100
        assert variant_results[1][0] is None  # No breakdown
        assert variant_results[1][1].key == "test"
        assert variant_results[1][1].number_of_samples == 150

    def test_multiple_results_with_breakdown(self):
        """Test processing multiple results with single breakdown."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
            breakdownFilter=BreakdownFilter(breakdowns=[Breakdown(property="$browser")]),
        )
        results = [
            ("control", "Chrome", 100, 250.5, 750.25),
            ("control", "Safari", 80, 200.0, 600.0),
            ("test", "Chrome", 150, 400.0, 1200.0),
            ("test", "Safari", 120, 300.0, 900.0),
        ]

        variant_results = get_variant_results(results, metric)

        assert len(variant_results) == 4
        assert variant_results[0][0] == ("Chrome",)
        assert variant_results[0][1].key == "control"
        assert variant_results[1][0] == ("Safari",)
        assert variant_results[1][1].key == "control"
        assert variant_results[2][0] == ("Chrome",)
        assert variant_results[2][1].key == "test"
        assert variant_results[3][0] == ("Safari",)
        assert variant_results[3][1].key == "test"

    def test_empty_results_list(self):
        """Test processing empty results list."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
        )
        results: list[tuple] = []

        variant_results = get_variant_results(results, metric)

        assert len(variant_results) == 0


class TestAggregateVariantsAcrossBreakdowns:
    """Tests for aggregate_variants_across_breakdowns() which aggregates per-breakdown stats into global stats."""

    def test_aggregate_mean_metrics_multiple_breakdowns(self):
        """Test aggregating mean metrics across multiple breakdown values."""
        variants = [
            (("Chrome",), ExperimentStatsBase(key="control", number_of_samples=100, sum=250.0, sum_squares=750.0)),
            (("Chrome",), ExperimentStatsBase(key="test", number_of_samples=120, sum=300.0, sum_squares=900.0)),
            (("Safari",), ExperimentStatsBase(key="control", number_of_samples=80, sum=200.0, sum_squares=600.0)),
            (("Safari",), ExperimentStatsBase(key="test", number_of_samples=90, sum=220.0, sum_squares=700.0)),
        ]

        aggregated = aggregate_variants_across_breakdowns(
            cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants)
        )

        # Should have 2 variants: control and test
        assert len(aggregated) == 2

        # Find control variant
        control = next(v for v in aggregated if v.key == "control")
        assert control.number_of_samples == 180  # 100 + 80
        assert control.sum == 450.0  # 250 + 200
        assert control.sum_squares == 1350.0  # 750 + 600

        # Find test variant
        test = next(v for v in aggregated if v.key == "test")
        assert test.number_of_samples == 210  # 120 + 90
        assert test.sum == 520.0  # 300 + 220
        assert test.sum_squares == 1600.0  # 900 + 700

    def test_aggregate_funnel_metrics_step_counts(self):
        """Test that funnel step_counts are aggregated element-wise."""
        variants = [
            (
                ("Chrome",),
                ExperimentStatsBase(
                    key="control", number_of_samples=100, sum=80.0, sum_squares=80.0, step_counts=[100, 85, 80]
                ),
            ),
            (
                ("Safari",),
                ExperimentStatsBase(
                    key="control", number_of_samples=80, sum=60.0, sum_squares=60.0, step_counts=[80, 70, 60]
                ),
            ),
        ]

        aggregated = aggregate_variants_across_breakdowns(
            cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants)
        )

        assert len(aggregated) == 1
        control = aggregated[0]
        assert control.key == "control"
        assert control.number_of_samples == 180  # 100 + 80
        assert control.sum == 140.0  # 80 + 60
        assert control.step_counts == [180, 155, 140]  # Element-wise sum

    def test_aggregate_funnel_metrics_with_step_sessions(self):
        """Test that funnel step_sessions are aggregated across breakdowns for actors view."""
        from posthog.schema import SessionData

        variants = [
            (
                ("Chrome",),
                ExperimentStatsBase(
                    key="control",
                    number_of_samples=100,
                    sum=80.0,
                    sum_squares=80.0,
                    step_counts=[100, 80],
                    step_sessions=[
                        [
                            SessionData(
                                person_id="user1", session_id="s1", event_uuid="e1", timestamp="2024-01-01T00:00:00Z"
                            )
                        ],
                        [
                            SessionData(
                                person_id="user1", session_id="s1", event_uuid="e2", timestamp="2024-01-01T00:00:01Z"
                            )
                        ],
                    ],
                ),
            ),
            (
                ("Safari",),
                ExperimentStatsBase(
                    key="control",
                    number_of_samples=80,
                    sum=60.0,
                    sum_squares=60.0,
                    step_counts=[80, 60],
                    step_sessions=[
                        [
                            SessionData(
                                person_id="user2", session_id="s2", event_uuid="e3", timestamp="2024-01-01T00:00:02Z"
                            )
                        ],
                        [
                            SessionData(
                                person_id="user2", session_id="s2", event_uuid="e4", timestamp="2024-01-01T00:00:03Z"
                            )
                        ],
                    ],
                ),
            ),
        ]

        aggregated = aggregate_variants_across_breakdowns(
            cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants)
        )

        assert len(aggregated) == 1
        control = aggregated[0]
        assert control.key == "control"
        assert control.step_counts == [180, 140]
        assert control.step_sessions is not None
        assert len(control.step_sessions) == 2  # Two steps
        assert len(control.step_sessions[0]) == 2  # Aggregated from both breakdowns
        assert len(control.step_sessions[1]) == 2  # Aggregated from both breakdowns
        assert control.step_sessions[0][0].person_id == "user1"
        assert control.step_sessions[0][1].person_id == "user2"

    def test_aggregate_ratio_metrics_denominator_fields(self):
        """Test that ratio metric denominator fields are aggregated correctly."""
        variants = [
            (
                ("Chrome",),
                ExperimentStatsBase(
                    key="control",
                    number_of_samples=100,
                    sum=50.0,
                    sum_squares=75.0,
                    denominator_sum=200.0,
                    denominator_sum_squares=500.0,
                    numerator_denominator_sum_product=120.0,
                ),
            ),
            (
                ("Safari",),
                ExperimentStatsBase(
                    key="control",
                    number_of_samples=80,
                    sum=40.0,
                    sum_squares=60.0,
                    denominator_sum=150.0,
                    denominator_sum_squares=400.0,
                    numerator_denominator_sum_product=90.0,
                ),
            ),
        ]

        aggregated = aggregate_variants_across_breakdowns(
            cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants)
        )

        assert len(aggregated) == 1
        control = aggregated[0]
        assert control.key == "control"
        assert control.number_of_samples == 180
        assert control.sum == 90.0  # 50 + 40
        assert control.sum_squares == 135.0  # 75 + 60
        assert control.denominator_sum == 350.0  # 200 + 150
        assert control.denominator_sum_squares == 900.0  # 500 + 400
        assert control.numerator_denominator_sum_product == 210.0  # 120 + 90

    def test_aggregate_multiple_variants_multiple_breakdowns(self):
        """Test aggregating multiple variants across multiple breakdowns."""
        variants = [
            (("Chrome",), ExperimentStatsBase(key="control", number_of_samples=100, sum=250.0, sum_squares=750.0)),
            (("Chrome",), ExperimentStatsBase(key="test", number_of_samples=120, sum=300.0, sum_squares=900.0)),
            (("Chrome",), ExperimentStatsBase(key="test-2", number_of_samples=110, sum=280.0, sum_squares=850.0)),
            (("Safari",), ExperimentStatsBase(key="control", number_of_samples=80, sum=200.0, sum_squares=600.0)),
            (("Safari",), ExperimentStatsBase(key="test", number_of_samples=90, sum=220.0, sum_squares=700.0)),
            (("Safari",), ExperimentStatsBase(key="test-2", number_of_samples=85, sum=210.0, sum_squares=650.0)),
        ]

        aggregated = aggregate_variants_across_breakdowns(
            cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants)
        )

        # Should have 3 variants
        assert len(aggregated) == 3

        # Verify each variant is aggregated correctly
        control = next(v for v in aggregated if v.key == "control")
        assert control.number_of_samples == 180
        assert control.sum == 450.0

        test = next(v for v in aggregated if v.key == "test")
        assert test.number_of_samples == 210
        assert test.sum == 520.0

        test_2 = next(v for v in aggregated if v.key == "test-2")
        assert test_2.number_of_samples == 195
        assert test_2.sum == 490.0

    def test_single_breakdown_no_aggregation_needed(self):
        """Test that single breakdown still works (no actual aggregation)."""
        variants = [
            (("Chrome",), ExperimentStatsBase(key="control", number_of_samples=100, sum=250.0, sum_squares=750.0)),
            (("Chrome",), ExperimentStatsBase(key="test", number_of_samples=120, sum=300.0, sum_squares=900.0)),
        ]

        aggregated = aggregate_variants_across_breakdowns(
            cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants)
        )

        assert len(aggregated) == 2
        control = next(v for v in aggregated if v.key == "control")
        assert control.number_of_samples == 100
        assert control.sum == 250.0

    def test_empty_variants_list(self):
        """Test that empty variants list returns empty aggregation."""
        variants: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]] = []

        aggregated = aggregate_variants_across_breakdowns(variants)

        assert len(aggregated) == 0

    def test_none_breakdown_values_ignored_in_grouping(self):
        """Test that None breakdown values are handled correctly."""
        variants = [
            (None, ExperimentStatsBase(key="control", number_of_samples=100, sum=250.0, sum_squares=750.0)),
            (None, ExperimentStatsBase(key="test", number_of_samples=120, sum=300.0, sum_squares=900.0)),
        ]

        aggregated = aggregate_variants_across_breakdowns(
            cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants)
        )

        # Should still aggregate by variant key
        assert len(aggregated) == 2
        control = next(v for v in aggregated if v.key == "control")
        assert control.number_of_samples == 100

    def test_preserves_variant_key_grouping(self):
        """Test that aggregation groups by variant key correctly."""
        # Same variant key across different breakdowns should be aggregated
        variants = [
            (("Chrome",), ExperimentStatsBase(key="control", number_of_samples=50, sum=100.0, sum_squares=200.0)),
            (("Safari",), ExperimentStatsBase(key="control", number_of_samples=50, sum=100.0, sum_squares=200.0)),
            (("Firefox",), ExperimentStatsBase(key="control", number_of_samples=50, sum=100.0, sum_squares=200.0)),
        ]

        aggregated = aggregate_variants_across_breakdowns(
            cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants)
        )

        # Should have only 1 variant (all have key="control")
        assert len(aggregated) == 1
        control = aggregated[0]
        assert control.key == "control"
        assert control.number_of_samples == 150  # 50 + 50 + 50
        assert control.sum == 300.0  # 100 + 100 + 100

    def test_aggregate_multiple_breakdown_dimensions(self):
        """Test aggregating across multiple breakdown dimensions (e.g., os + browser)."""
        variants = [
            (
                ("MacOS", "Chrome"),
                ExperimentStatsBase(key="control", number_of_samples=50, sum=100.0, sum_squares=200.0),
            ),
            (
                ("MacOS", "Safari"),
                ExperimentStatsBase(key="control", number_of_samples=40, sum=80.0, sum_squares=160.0),
            ),
            (
                ("Windows", "Chrome"),
                ExperimentStatsBase(key="control", number_of_samples=60, sum=120.0, sum_squares=240.0),
            ),
            (
                ("Windows", "Firefox"),
                ExperimentStatsBase(key="control", number_of_samples=30, sum=60.0, sum_squares=120.0),
            ),
        ]

        aggregated = aggregate_variants_across_breakdowns(
            cast(list[tuple[tuple[str, ...] | None, ExperimentStatsBase]], variants)
        )

        # All have same variant key, should aggregate into one
        assert len(aggregated) == 1
        control = aggregated[0]
        assert control.key == "control"
        assert control.number_of_samples == 180  # 50+40+60+30
        assert control.sum == 360.0  # 100+80+120+60
        assert control.sum_squares == 720.0  # 200+160+240+120


class TestValidateVariantResult:
    """Tests for validate_variant_result() validation logic."""

    def test_retention_metric_with_insufficient_successes(self):
        """Test that retention metrics with < 5 successes get NOT_ENOUGH_METRIC_DATA validation failure."""
        metric = ExperimentRetentionMetric(
            start_event=EventsNode(event="signup", math=ExperimentMetricMathType.TOTAL),
            completion_event=EventsNode(event="login", math=ExperimentMetricMathType.TOTAL),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
        )

        # Create variant with 100 samples but only 4 successes (< 5)
        variant = ExperimentStatsBase(
            key="test",
            number_of_samples=100,
            sum=4,  # Only 4 retained users
            sum_squares=4,
        )

        result = validate_variant_result(variant, metric, is_baseline=False)

        # Should have NOT_ENOUGH_METRIC_DATA validation failure
        assert result.validation_failures is not None
        assert ExperimentStatsValidationFailure.NOT_ENOUGH_METRIC_DATA in result.validation_failures

    def test_retention_metric_with_sufficient_successes(self):
        """Test that retention metrics with >= 5 successes pass validation."""
        metric = ExperimentRetentionMetric(
            start_event=EventsNode(event="signup", math=ExperimentMetricMathType.TOTAL),
            completion_event=EventsNode(event="login", math=ExperimentMetricMathType.TOTAL),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
        )

        # Create variant with 100 samples and 5 successes (>= 5)
        variant = ExperimentStatsBase(
            key="test",
            number_of_samples=100,
            sum=5,  # 5 retained users
            sum_squares=5,
        )

        result = validate_variant_result(variant, metric, is_baseline=False)

        # Should NOT have NOT_ENOUGH_METRIC_DATA validation failure
        assert result.validation_failures is not None
        assert ExperimentStatsValidationFailure.NOT_ENOUGH_METRIC_DATA not in result.validation_failures

    def test_funnel_metric_with_insufficient_successes(self):
        """Test that funnel metrics with < 5 successes get NOT_ENOUGH_METRIC_DATA validation failure."""
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
                EventsNode(event="signup", math=ExperimentMetricMathType.TOTAL),
            ]
        )

        # Create variant with 100 samples but only 3 conversions (< 5)
        variant = ExperimentStatsBase(
            key="test",
            number_of_samples=100,
            sum=3,  # Only 3 conversions
            sum_squares=3,
        )

        result = validate_variant_result(variant, metric, is_baseline=False)

        # Should have NOT_ENOUGH_METRIC_DATA validation failure
        assert result.validation_failures is not None
        assert ExperimentStatsValidationFailure.NOT_ENOUGH_METRIC_DATA in result.validation_failures

    def test_mean_metric_no_minimum_success_validation(self):
        """Test that mean metrics don't require minimum successes (continuous metrics)."""
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
        )

        # Create variant with low sum (< 5) - should NOT trigger validation failure
        variant = ExperimentStatsBase(
            key="test",
            number_of_samples=100,
            sum=2.5,  # Low sum, but this is continuous data
            sum_squares=10.0,
        )

        result = validate_variant_result(variant, metric, is_baseline=False)

        # Mean metrics should NOT have NOT_ENOUGH_METRIC_DATA validation failure
        assert result.validation_failures is not None
        assert ExperimentStatsValidationFailure.NOT_ENOUGH_METRIC_DATA not in result.validation_failures

    def test_validation_not_enough_exposures(self):
        """Test that all metrics trigger NOT_ENOUGH_EXPOSURES with < 50 samples."""
        metric = ExperimentRetentionMetric(
            start_event=EventsNode(event="signup", math=ExperimentMetricMathType.TOTAL),
            completion_event=EventsNode(event="login", math=ExperimentMetricMathType.TOTAL),
            retention_window_start=1,
            retention_window_end=7,
            retention_window_unit=FunnelConversionWindowTimeUnit.DAY,
            start_handling=StartHandling.FIRST_SEEN,
        )

        # Create variant with only 30 samples (< 50)
        variant = ExperimentStatsBase(
            key="test",
            number_of_samples=30,
            sum=20,
            sum_squares=20,
        )

        result = validate_variant_result(variant, metric, is_baseline=False)

        # Should have NOT_ENOUGH_EXPOSURES validation failure
        assert result.validation_failures is not None
        assert ExperimentStatsValidationFailure.NOT_ENOUGH_EXPOSURES in result.validation_failures
