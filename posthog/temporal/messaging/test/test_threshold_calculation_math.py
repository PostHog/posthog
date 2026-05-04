"""
Tests for mathematical correctness of threshold calculations with caching.

Verifies that the integration between quantiles caching and threshold calculation
produces consistent, non-overlapping tier boundaries.
"""

import pytest
from unittest.mock import Mock, patch

from posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator import (
    QueryPercentileThresholdsInput,
    calculate_percentile_thresholds,
)


class TestThresholdCalculationMath:
    """Test mathematical correctness of threshold calculations."""

    @pytest.mark.asyncio
    async def test_tier_boundaries_no_overlap_with_caching(self):
        """Test that cached quantiles produce non-overlapping tier boundaries."""
        # Realistic cohort duration data (milliseconds)
        durations = [
            100,
            150,
            200,
            250,
            300,
            350,
            400,
            450,
            500,
            550,  # p0-p10
            600,
            650,
            700,
            750,
            800,
            850,
            900,
            950,
            1000,
            1050,  # p10-p30
            1100,
            1200,
            1300,
            1400,
            1500,
            1600,
            1700,
            1800,
            1900,
            2000,  # p30-p50
            2200,
            2400,
            2600,
            2800,
            3000,
            3200,
            3400,
            3600,
            3800,
            4000,  # p50-p70
            4500,
            5000,
            5500,
            6000,
            6500,
            7000,
            7500,
            8000,
            8500,
            9000,  # p70-p90
            10000,
            12000,
            14000,
            16000,
            18000,
            20000,
            25000,
            30000,
            40000,
            50000,  # p90-p100
        ]

        # Mock cached quantiles to ensure consistency
        import statistics

        expected_quantiles = statistics.quantiles(durations, n=100, method="inclusive")

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_queryset = Mock()
            mock_queryset.values_list.return_value = durations
            mock_cohort.objects.filter.return_value = mock_queryset

            with patch("posthog.temporal.messaging.quantiles_storage.get_or_calculate_quantiles") as mock_get_quantiles:
                mock_get_quantiles.return_value = expected_quantiles

                # Calculate thresholds for all tiers
                p0_p50_input = QueryPercentileThresholdsInput(min_percentile=0.0, max_percentile=50.0)
                p50_p80_input = QueryPercentileThresholdsInput(min_percentile=50.0, max_percentile=80.0)
                p80_p90_input = QueryPercentileThresholdsInput(min_percentile=80.0, max_percentile=90.0)
                p90_p100_input = QueryPercentileThresholdsInput(min_percentile=90.0, max_percentile=100.0)

                p0_p50_thresholds = await calculate_percentile_thresholds(p0_p50_input)
                p50_p80_thresholds = await calculate_percentile_thresholds(p50_p80_input)
                p80_p90_thresholds = await calculate_percentile_thresholds(p80_p90_input)
                p90_p100_thresholds = await calculate_percentile_thresholds(p90_p100_input)

                # Verify all calculations succeeded
                assert p0_p50_thresholds is not None
                assert p50_p80_thresholds is not None
                assert p80_p90_thresholds is not None
                assert p90_p100_thresholds is not None

                # Verify tier boundaries align perfectly (no gaps or overlaps)
                assert p0_p50_thresholds.min_threshold_ms == 0  # p0 is always 0
                assert p0_p50_thresholds.max_threshold_ms == p50_p80_thresholds.min_threshold_ms, (
                    f"p0-p50 max ({p0_p50_thresholds.max_threshold_ms}) should equal p50-p80 min ({p50_p80_thresholds.min_threshold_ms})"
                )
                assert p50_p80_thresholds.max_threshold_ms == p80_p90_thresholds.min_threshold_ms, (
                    f"p50-p80 max ({p50_p80_thresholds.max_threshold_ms}) should equal p80-p90 min ({p80_p90_thresholds.min_threshold_ms})"
                )
                assert p80_p90_thresholds.max_threshold_ms == p90_p100_thresholds.min_threshold_ms, (
                    f"p80-p90 max ({p80_p90_thresholds.max_threshold_ms}) should equal p90-p100 min ({p90_p100_thresholds.min_threshold_ms})"
                )

                # Verify p100 is the actual maximum
                assert p90_p100_thresholds.max_threshold_ms == max(durations), (
                    f"p100 value ({p90_p100_thresholds.max_threshold_ms}) should equal max duration ({max(durations)})"
                )

    @pytest.mark.asyncio
    async def test_consistent_calculations_across_calls(self):
        """Test that multiple calls with same cache return identical results."""
        durations = list(range(100, 2000, 50))  # Clean test data

        import statistics

        expected_quantiles = statistics.quantiles(durations, n=100, method="inclusive")

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_queryset = Mock()
            mock_queryset.values_list.return_value = durations
            mock_cohort.objects.filter.return_value = mock_queryset

            with patch("posthog.temporal.messaging.quantiles_storage.get_or_calculate_quantiles") as mock_get_quantiles:
                # Ensure cache returns same quantiles every time
                mock_get_quantiles.return_value = expected_quantiles

                # Multiple workflows calculating p50-p80 thresholds
                input_data = QueryPercentileThresholdsInput(min_percentile=50.0, max_percentile=80.0)

                result1 = await calculate_percentile_thresholds(input_data)
                result2 = await calculate_percentile_thresholds(input_data)
                result3 = await calculate_percentile_thresholds(input_data)

                # All results should be identical
                assert result1.min_threshold_ms == result2.min_threshold_ms == result3.min_threshold_ms
                assert result1.max_threshold_ms == result2.max_threshold_ms == result3.max_threshold_ms

                # Cache should only be called once per calculation (or multiple times but returning same data)
                assert mock_get_quantiles.call_count >= 3

    @pytest.mark.asyncio
    async def test_percentile_edge_cases(self):
        """Test edge cases in percentile calculations."""
        durations = [500, 1000, 1500]  # Minimal data

        import statistics

        expected_quantiles = statistics.quantiles(durations, n=100, method="inclusive")

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_queryset = Mock()
            mock_queryset.values_list.return_value = durations
            mock_cohort.objects.filter.return_value = mock_queryset

            with patch("posthog.temporal.messaging.quantiles_storage.get_or_calculate_quantiles") as mock_get_quantiles:
                mock_get_quantiles.return_value = expected_quantiles

                # Test p0 edge case
                p0_input = QueryPercentileThresholdsInput(min_percentile=0.0, max_percentile=10.0)
                p0_result = await calculate_percentile_thresholds(p0_input)
                assert p0_result.min_threshold_ms == 0  # p0 should always be 0

                # Test p100 edge case
                p100_input = QueryPercentileThresholdsInput(min_percentile=99.0, max_percentile=100.0)
                p100_result = await calculate_percentile_thresholds(p100_input)
                assert p100_result.max_threshold_ms == max(durations)  # p100 should be actual max

    @pytest.mark.asyncio
    async def test_threshold_calculation_with_cache_failure(self):
        """Test threshold calculation when cache fails."""
        durations = [100, 200, 300, 400, 500]

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_queryset = Mock()
            mock_queryset.values_list.return_value = durations
            mock_cohort.objects.filter.return_value = mock_queryset

            with patch("posthog.temporal.messaging.quantiles_storage.get_or_calculate_quantiles") as mock_get_quantiles:
                # Simulate cache failure
                mock_get_quantiles.return_value = None

                input_data = QueryPercentileThresholdsInput(min_percentile=25.0, max_percentile=75.0)
                result = await calculate_percentile_thresholds(input_data)

                # Should return None when quantiles calculation fails
                assert result is None

    @pytest.mark.asyncio
    async def test_realistic_scenario_verification(self):
        """Test with realistic data that previously caused overlaps."""
        # Simulate the problematic scenario from the bug report
        durations = [
            # Fast cohorts (will be in p0-p50)
            100,
            150,
            200,
            250,
            300,
            350,
            400,
            450,
            498,  # p0-p50 should max around 498
            # Medium cohorts (should be in p50-p80)
            501,
            520,
            540,
            560,
            580,
            601,  # p50-p80 should start around 500-501, max around 601
            # Slow cohorts
            650,
            700,
            800,
            900,
            1000,
            1200,
            1500,
            2000,
        ]

        import statistics

        expected_quantiles = statistics.quantiles(durations, n=100, method="inclusive")

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_queryset = Mock()
            mock_queryset.values_list.return_value = durations
            mock_cohort.objects.filter.return_value = mock_queryset

            with patch("posthog.temporal.messaging.quantiles_storage.get_or_calculate_quantiles") as mock_get_quantiles:
                mock_get_quantiles.return_value = expected_quantiles

                # Calculate the problematic tiers
                p0_p50_input = QueryPercentileThresholdsInput(min_percentile=0.0, max_percentile=50.0)
                p50_p80_input = QueryPercentileThresholdsInput(min_percentile=50.0, max_percentile=80.0)

                p0_p50_result = await calculate_percentile_thresholds(p0_p50_input)
                p50_p80_result = await calculate_percentile_thresholds(p50_p80_input)

                # Verify no overlap (the bug we fixed)
                assert p0_p50_result.max_threshold_ms == p50_p80_result.min_threshold_ms, (
                    f"OVERLAP DETECTED: p0-p50 max ({p0_p50_result.max_threshold_ms}) != p50-p80 min ({p50_p80_result.min_threshold_ms})"
                )

                # Verify the ranges make sense
                assert p0_p50_result.min_threshold_ms == 0
                assert p0_p50_result.max_threshold_ms < p50_p80_result.max_threshold_ms
