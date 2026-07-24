"""
Tests for quantiles storage module.

Tests the mathematical correctness of percentile calculations and Redis caching logic.
"""

import json
import statistics

import pytest
from unittest.mock import Mock, patch

from posthog.temporal.messaging.quantiles_storage import (
    CachedQuantiles,
    _get_cache_key,
    _get_current_hour_bucket,
    _get_lock_key,
    get_cached_quantiles_or_calculate,
    get_quantiles,
    store_quantiles,
)


class TestQuantilesMath:
    """Test the mathematical correctness of percentile calculations."""

    @pytest.mark.parametrize(
        "durations,description",
        [
            (list(range(1, 101)), "sequential 1-100"),
            (
                [100, 200, 300, 500, 800, 1000, 1500, 2000, 3000, 5000, 8000, 10000, 15000, 20000, 30000],
                "realistic durations",
            ),
            ([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], "known dataset"),
            ([1000] * 50, "identical values"),
            ([100, 900], "two values"),
            (
                [
                    50,
                    75,
                    100,
                    125,
                    150,
                    200,
                    250,
                    300,
                    350,
                    400,
                    450,
                    500,
                    550,
                    600,
                    650,
                    700,
                    750,
                    800,
                    850,
                    900,
                    1000,
                    1200,
                    1400,
                    1600,
                    1800,
                    2000,
                    2500,
                    3000,
                    3500,
                    4000,
                    5000,
                    6000,
                    8000,
                    10000,
                    15000,
                    20000,
                ],
                "real scenario cohort durations",
            ),
        ],
    )
    def test_percentile_math_correctness(self, durations, description):
        """Test mathematical correctness of percentile calculations with various datasets."""
        quantiles = statistics.quantiles(durations, n=100, method="inclusive")

        # Test tier boundaries don't overlap
        p50_value = quantiles[50 - 1]
        p80_value = quantiles[80 - 1]
        p90_value = quantiles[90 - 1]

        p0_min = 0
        p50_int = int(p50_value)
        p80_int = int(p80_value)
        p90_int = int(p90_value)
        p100_int = int(max(durations))

        # Verify tier boundaries don't overlap
        tier_boundaries = [
            ("p0-p50", p0_min, p50_int),
            ("p50-p80", p50_int, p80_int),
            ("p80-p90", p80_int, p90_int),
            ("p90-p100", p90_int, p100_int),
        ]

        for i, (tier_name, tier_min, tier_max) in enumerate(tier_boundaries):
            # Each tier should have min <= max
            assert tier_min <= tier_max, f"{description} - {tier_name}: min ({tier_min}) should be <= max ({tier_max})"

            # Adjacent tiers should connect seamlessly
            if i > 0:
                prev_tier_name, prev_tier_min, prev_tier_max = tier_boundaries[i - 1]
                assert prev_tier_max == tier_min, (
                    f"{description} - {prev_tier_name} max ({prev_tier_max}) should equal {tier_name} min ({tier_min})"
                )

        # Test monotonic increase of percentiles
        test_percentiles = [10, 25, 50, 75, 90, 95, 99]
        prev_value = 0
        for p in test_percentiles:
            current_value = quantiles[p - 1]
            assert prev_value <= current_value, (
                f"{description} - p{p - 10 if p > 10 else 0} ({prev_value}) should be <= p{p} ({current_value})"
            )
            prev_value = current_value

        # Verify p100 is the actual maximum
        p99 = quantiles[99 - 1]
        p100 = max(durations)
        assert p99 <= p100, f"{description} - p99 ({p99}) should be <= p100 ({p100})"


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
        """Test 2-hour bucket format is correct."""
        with patch("posthog.temporal.messaging.quantiles_storage.dt") as mock_dt:
            # Test hour 14 (even) -> bucket starts at 14
            mock_now = Mock()
            mock_now.hour = 14
            mock_now.strftime.return_value = "2024-01-15:14"
            mock_dt.datetime.now.return_value = mock_now

            result = _get_current_hour_bucket()
            assert result == "2024-01-15:14"

            # Test hour 15 (odd) -> bucket starts at 14
            mock_now.hour = 15
            mock_now.strftime.return_value = "2024-01-15:14"

            result = _get_current_hour_bucket()
            assert result == "2024-01-15:14"

            mock_dt.datetime.now.assert_called_with(mock_dt.UTC)

    @patch("posthog.temporal.messaging.quantiles_storage.get_client")
    def test_store_quantiles_success(self, mock_get_client):
        """Test successful quantile storage."""
        mock_redis = Mock()
        mock_redis.set.return_value = True  # Lock acquired
        mock_redis.exists.return_value = False  # No existing cache
        mock_get_client.return_value = mock_redis

        quantiles = [100.0, 200.0, 300.0]
        result = store_quantiles(quantiles, max_value=400, hour_bucket="2024-01-15:14")

        assert result is True
        mock_redis.set.assert_called_once()  # Lock
        mock_redis.setex.assert_called_once()  # Store data
        # Lock release uses an atomic Lua compare-and-delete via redis_client.eval
        mock_redis.eval.assert_called_once()
        # Persisted payload is the new dict format including max_value
        stored_payload = json.loads(mock_redis.setex.call_args.args[2])
        assert stored_payload == {"quantiles": quantiles, "max_value": 400}

    @patch("posthog.temporal.messaging.quantiles_storage.get_client")
    def test_store_quantiles_lock_contention(self, mock_get_client):
        """Test behavior when lock is already held."""
        mock_redis = Mock()
        mock_redis.set.return_value = False  # Lock not acquired
        mock_get_client.return_value = mock_redis

        quantiles = [100.0, 200.0, 300.0]
        result = store_quantiles(quantiles, max_value=400, hour_bucket="2024-01-15:14")

        assert result is False
        mock_redis.setex.assert_not_called()  # Should not store

    @patch("posthog.temporal.messaging.quantiles_storage.get_client")
    def test_get_quantiles_hit(self, mock_get_client):
        """Test successful cache retrieval."""
        mock_redis = Mock()
        cached_data = json.dumps({"quantiles": [100.0, 200.0, 300.0], "max_value": 400})
        mock_redis.get.return_value = cached_data
        mock_get_client.return_value = mock_redis

        result = get_quantiles("2024-01-15:14")

        assert result == CachedQuantiles(quantiles=[100.0, 200.0, 300.0], max_value=400)

    @patch("posthog.temporal.messaging.quantiles_storage.get_client")
    def test_get_quantiles_miss(self, mock_get_client):
        """Test cache miss."""
        mock_redis = Mock()
        mock_redis.get.return_value = None
        mock_get_client.return_value = mock_redis

        result = get_quantiles("2024-01-15:14")

        assert result is None

    @patch("posthog.temporal.messaging.quantiles_storage.get_client")
    def test_get_quantiles_legacy_format_is_treated_as_miss(self, mock_get_client):
        """Legacy bare-list cache entries should be discarded so callers recalculate
        with the new max_value contract instead of silently mixing formats."""
        mock_redis = Mock()
        mock_redis.get.return_value = json.dumps([100.0, 200.0, 300.0])
        mock_get_client.return_value = mock_redis

        result = get_quantiles("2024-01-15:14")

        assert result is None
        mock_redis.delete.assert_called_once()

    @patch("posthog.temporal.messaging.quantiles_storage.get_client")
    @patch("posthog.temporal.messaging.quantiles_storage.time.sleep")
    def test_get_or_calculate_race_condition_handling(self, mock_sleep, mock_get_client):
        """Test race condition handling with retry logic."""
        mock_redis = Mock()
        mock_get_client.return_value = mock_redis

        with patch("statistics.quantiles", return_value=[100.0, 200.0, 300.0]):
            cached_payload = json.dumps({"quantiles": [100.0, 200.0, 300.0], "max_value": 250})
            # First call: cache miss for current bucket
            # Second call: cache miss for previous bucket
            # Third call: lock contention, then cache hit after retry
            mock_redis.get.side_effect = [
                None,  # Initial cache miss (current hour)
                None,  # Previous hour cache miss
                None,  # Still miss after first store attempt fails
                cached_payload,  # Hit after retry
            ]
            mock_redis.set.side_effect = [False, True]  # First lock fails, second succeeds
            mock_redis.exists.return_value = False

            durations = [50, 100, 150, 200, 250]
            result = get_cached_quantiles_or_calculate(durations, "2024-01-15:14", max_retries=2)

            assert result == CachedQuantiles(quantiles=[100.0, 200.0, 300.0], max_value=250)
            assert mock_sleep.call_count == 1  # Should retry once

    def test_race_condition_scenario_realistic(self):
        """Test realistic race condition scenario with multiple workflows."""
        # This test simulates what happens when p0-p50 and p50-p80 workflows
        # start at the same time and both try to calculate quantiles

        durations = list(range(100, 1000, 10))  # Realistic duration spread
        cached_payload = json.dumps({"quantiles": [200.0, 400.0, 600.0], "max_value": 990})

        with patch("posthog.temporal.messaging.quantiles_storage.get_client") as mock_get_client:
            mock_redis = Mock()
            mock_get_client.return_value = mock_redis
            mock_redis.exists.return_value = False
            # Workflow 1: both current and previous-hour buckets miss → calculates and stores;
            # Workflow 2: current-hour bucket hits the populated cache.
            mock_redis.get.side_effect = [
                None,  # workflow 1: current bucket miss
                None,  # workflow 1: previous-hour fallback miss
                cached_payload,  # workflow 2: current bucket hit
            ]
            mock_redis.set.side_effect = [True]  # workflow 1 acquires lock

            # First workflow calculates and stores
            result1 = get_cached_quantiles_or_calculate(durations, "2024-01-15:14")

            # Second workflow gets from cache
            result2 = get_cached_quantiles_or_calculate(durations, "2024-01-15:14")

            # Both should be populated; workflow 2's result is the canonical cached value
            assert result1 is not None
            assert result2 == CachedQuantiles(quantiles=[200.0, 400.0, 600.0], max_value=990)
