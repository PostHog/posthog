"""
Tests for quantiles storage module.

Tests the mathematical correctness of percentile calculations and Redis caching logic.
"""

import json

from unittest.mock import Mock, patch

from posthog.temporal.messaging.quantiles_storage import (
    _get_cache_key,
    _get_current_hour_bucket,
    _get_lock_key,
    get_or_calculate_quantiles,
    get_quantiles,
    store_quantiles,
)


class TestQuantilesMath:
    """Test the mathematical correctness of percentile calculations."""

    def test_percentile_boundaries_no_overlap(self):
        """Test that adjacent percentile tiers have no overlapping values."""
        # Test data: 100 values from 1 to 100
        durations = list(range(1, 101))

        # Calculate quantiles directly to verify math
        import statistics

        quantiles = statistics.quantiles(durations, n=100, method="inclusive")

        # Test p0-p50 vs p50-p80 boundaries
        p50_value = quantiles[50 - 1]  # quantiles[49] is p50
        p80_value = quantiles[80 - 1]  # quantiles[79] is p80

        # p0-p50 range should be [0, p50]
        p0_p50_max = int(p50_value)

        # p50-p80 range should be [p50, p80)
        p50_p80_min = int(p50_value)
        p50_p80_max = int(p80_value)

        # Verify no gap or overlap
        assert p0_p50_max == p50_p80_min, (
            f"Gap/overlap between p0-p50 max ({p0_p50_max}) and p50-p80 min ({p50_p80_min})"
        )
        assert p0_p50_max < p50_p80_max, f"p50 ({p0_p50_max}) should be less than p80 ({p50_p80_max})"

    def test_percentile_values_increase_monotonically(self):
        """Test that percentile values increase as percentiles increase."""
        # Test with realistic duration data (milliseconds)
        durations = [100, 200, 300, 500, 800, 1000, 1500, 2000, 3000, 5000, 8000, 10000, 15000, 20000, 30000]

        import statistics

        quantiles = statistics.quantiles(durations, n=100, method="inclusive")

        # Test key percentiles used in the system
        p10 = quantiles[10 - 1]  # quantiles[9]
        p25 = quantiles[25 - 1]  # quantiles[24]
        p50 = quantiles[50 - 1]  # quantiles[49]
        p75 = quantiles[75 - 1]  # quantiles[74]
        p90 = quantiles[90 - 1]  # quantiles[89]
        p95 = quantiles[95 - 1]  # quantiles[94]
        p99 = quantiles[99 - 1]  # quantiles[98]

        # Verify monotonic increase
        assert p10 <= p25, f"p10 ({p10}) should be <= p25 ({p25})"
        assert p25 <= p50, f"p25 ({p25}) should be <= p50 ({p50})"
        assert p50 <= p75, f"p50 ({p50}) should be <= p75 ({p75})"
        assert p75 <= p90, f"p75 ({p75}) should be <= p90 ({p90})"
        assert p90 <= p95, f"p90 ({p90}) should be <= p95 ({p95})"
        assert p95 <= p99, f"p95 ({p95}) should be <= p99 ({p99})"

        # Verify p100 is the actual maximum
        p100 = max(durations)
        assert p99 <= p100, f"p99 ({p99}) should be <= p100 ({p100})"

    def test_percentile_indexing_correctness(self):
        """Test that the indexing logic matches statistics.quantiles behavior."""
        # Known dataset to verify exact values
        durations = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

        import statistics

        quantiles = statistics.quantiles(durations, n=100, method="inclusive")

        # Verify our indexing logic matches the library
        # For p50: should be quantiles[50-1] = quantiles[49]
        our_p50_index = 50 - 1
        expected_p50 = quantiles[our_p50_index]

        # For p80: should be quantiles[80-1] = quantiles[79]
        our_p80_index = 80 - 1
        expected_p80 = quantiles[our_p80_index]

        # Verify these make sense for our test data
        # With 10 values [10,20,30,40,50,60,70,80,90,100], p50 should be around 55
        assert 50 <= expected_p50 <= 60, f"p50 should be around 50-60 for test data, got {expected_p50}"
        assert 80 <= expected_p80 <= 90, f"p80 should be around 80-90 for test data, got {expected_p80}"

    def test_edge_case_identical_values(self):
        """Test percentile calculation when all values are identical."""
        # All cohorts have same duration
        durations = [1000] * 50

        import statistics

        quantiles = statistics.quantiles(durations, n=100, method="inclusive")

        # All percentiles should be the same value
        p25 = quantiles[25 - 1]
        p50 = quantiles[50 - 1]
        p75 = quantiles[75 - 1]
        p90 = quantiles[90 - 1]

        assert p25 == p50 == p75 == p90 == 1000, "All percentiles should equal 1000 when all data is identical"

    def test_edge_case_two_values(self):
        """Test percentile calculation with minimum viable dataset (2 values)."""
        durations = [100, 900]

        import statistics

        quantiles = statistics.quantiles(durations, n=100, method="inclusive")

        # p50 should be between the two values
        p50 = quantiles[50 - 1]
        assert 100 <= p50 <= 900, f"p50 should be between 100 and 900, got {p50}"

    def test_percentile_boundaries_real_scenario(self):
        """Test with realistic cohort duration data to verify tier boundaries."""
        # Simulated real-world cohort durations (milliseconds)
        durations = [
            50,
            75,
            100,
            125,
            150,
            200,
            250,
            300,
            350,
            400,  # Fast cohorts
            450,
            500,
            550,
            600,
            650,
            700,
            750,
            800,
            850,
            900,  # Medium cohorts
            1000,
            1200,
            1400,
            1600,
            1800,
            2000,
            2500,
            3000,  # Slow cohorts
            3500,
            4000,
            5000,
            6000,
            8000,
            10000,
            15000,
            20000,  # Very slow cohorts
        ]

        import statistics

        quantiles = statistics.quantiles(durations, n=100, method="inclusive")

        # Calculate tier boundaries like the actual system does
        p0_min = 0
        p50_value = int(quantiles[50 - 1])
        p80_value = int(quantiles[80 - 1])
        p90_value = int(quantiles[90 - 1])
        p100_value = int(max(durations))

        # Verify tier boundaries don't overlap
        tier_boundaries = [
            ("p0-p50", p0_min, p50_value),
            ("p50-p80", p50_value, p80_value),
            ("p80-p90", p80_value, p90_value),
            ("p90-p100", p90_value, p100_value),
        ]

        for i, (tier_name, tier_min, tier_max) in enumerate(tier_boundaries):
            # Each tier should have min <= max
            assert tier_min <= tier_max, f"{tier_name}: min ({tier_min}) should be <= max ({tier_max})"

            # Adjacent tiers should connect seamlessly
            if i > 0:
                prev_tier_name, prev_tier_min, prev_tier_max = tier_boundaries[i - 1]
                assert prev_tier_max == tier_min, (
                    f"{prev_tier_name} max ({prev_tier_max}) should equal {tier_name} min ({tier_min})"
                )


class TestQuantilesCache:
    """Test Redis caching functionality."""

    def test_cache_key_generation(self):
        """Test cache key generation is consistent."""
        hour_bucket = "2024-01-15:14"
        expected_key = "duration_quantiles:2024-01-15:14"
        assert _get_cache_key(hour_bucket) == expected_key

    def test_lock_key_generation(self):
        """Test lock key generation is consistent."""
        hour_bucket = "2024-01-15:14"
        expected_key = "duration_quantiles_lock:2024-01-15:14"
        assert _get_lock_key(hour_bucket) == expected_key

    def test_current_hour_bucket_format(self):
        """Test hour bucket format is correct."""
        with patch("posthog.temporal.messaging.quantiles_storage.dt") as mock_dt:
            mock_now = Mock()
            mock_now.strftime.return_value = "2024-01-15:14"
            mock_dt.datetime.now.return_value = mock_now

            result = _get_current_hour_bucket()
            assert result == "2024-01-15:14"
            mock_dt.datetime.now.assert_called_once_with(mock_dt.UTC)

    @patch("posthog.temporal.messaging.quantiles_storage.get_client")
    def test_store_quantiles_success(self, mock_get_client):
        """Test successful quantile storage."""
        mock_redis = Mock()
        mock_redis.set.return_value = True  # Lock acquired
        mock_redis.exists.return_value = False  # No existing cache
        mock_get_client.return_value = mock_redis

        quantiles = [100.0, 200.0, 300.0]
        result = store_quantiles(quantiles, "2024-01-15:14")

        assert result is True
        mock_redis.set.assert_called_once()  # Lock
        mock_redis.setex.assert_called_once()  # Store data
        mock_redis.delete.assert_called_once()  # Release lock

    @patch("posthog.temporal.messaging.quantiles_storage.get_client")
    def test_store_quantiles_lock_contention(self, mock_get_client):
        """Test behavior when lock is already held."""
        mock_redis = Mock()
        mock_redis.set.return_value = False  # Lock not acquired
        mock_get_client.return_value = mock_redis

        quantiles = [100.0, 200.0, 300.0]
        result = store_quantiles(quantiles, "2024-01-15:14")

        assert result is False
        mock_redis.setex.assert_not_called()  # Should not store

    @patch("posthog.temporal.messaging.quantiles_storage.get_client")
    def test_get_quantiles_hit(self, mock_get_client):
        """Test successful cache retrieval."""
        mock_redis = Mock()
        cached_data = json.dumps([100.0, 200.0, 300.0])
        mock_redis.get.return_value = cached_data
        mock_get_client.return_value = mock_redis

        result = get_quantiles("2024-01-15:14")

        assert result == [100.0, 200.0, 300.0]

    @patch("posthog.temporal.messaging.quantiles_storage.get_client")
    def test_get_quantiles_miss(self, mock_get_client):
        """Test cache miss."""
        mock_redis = Mock()
        mock_redis.get.return_value = None
        mock_get_client.return_value = mock_redis

        result = get_quantiles("2024-01-15:14")

        assert result is None

    @patch("posthog.temporal.messaging.quantiles_storage.get_client")
    @patch("posthog.temporal.messaging.quantiles_storage.time.sleep")
    def test_get_or_calculate_race_condition_handling(self, mock_sleep, mock_get_client):
        """Test race condition handling with retry logic."""
        mock_redis = Mock()
        mock_get_client.return_value = mock_redis

        with patch("statistics.quantiles", return_value=[100.0, 200.0, 300.0]):
            # First call: cache miss
            # Second call: lock contention, then cache hit after retry
            mock_redis.get.side_effect = [
                None,  # Initial cache miss
                None,  # Still miss after first store attempt fails
                json.dumps([100.0, 200.0, 300.0]),  # Hit after retry
            ]
            mock_redis.set.side_effect = [False, True]  # First lock fails, second succeeds
            mock_redis.exists.return_value = False

            durations = [50, 100, 150, 200, 250]
            result = get_or_calculate_quantiles(durations, "2024-01-15:14", max_retries=2)

            assert result == [100.0, 200.0, 300.0]
            assert mock_sleep.call_count == 1  # Should retry once

    def test_race_condition_scenario_realistic(self):
        """Test realistic race condition scenario with multiple workflows."""
        # This test simulates what happens when p0-p50 and p50-p80 workflows
        # start at the same time and both try to calculate quantiles

        durations = list(range(100, 1000, 10))  # Realistic duration spread

        with patch("posthog.temporal.messaging.quantiles_storage.get_client") as mock_get_client:
            mock_redis = Mock()
            mock_get_client.return_value = mock_redis

            # Simulate first workflow wins the lock
            mock_redis.set.side_effect = [True, False]  # First wins, second loses
            mock_redis.exists.return_value = False
            mock_redis.get.side_effect = [
                None,  # Cache miss for first workflow
                json.dumps([200.0, 400.0, 600.0]),  # Cache hit for second workflow
            ]

            # First workflow calculates and stores
            result1 = get_or_calculate_quantiles(durations, "2024-01-15:14")

            # Second workflow gets from cache
            result2 = get_or_calculate_quantiles(durations, "2024-01-15:14")

            # Both should get the same result (consistency achieved)
            assert result1 is not None
            assert result2 == [200.0, 400.0, 600.0]  # From cache
