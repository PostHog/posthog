"""
Integration tests for quantiles storage with real Redis concurrency scenarios.

Tests actual Redis operations and thread-based concurrency to verify
our locking mechanism works in practice.
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from unittest.mock import patch

from posthog.redis import get_client
from posthog.temporal.messaging.quantiles_storage import (
    CachedQuantiles,
    _get_cache_key,
    _get_lock_key,
    get_cached_quantiles_or_calculate,
    get_quantiles,
    store_quantiles,
)


@pytest.mark.django_db
class TestQuantilesConcurrencyIntegration:
    """Integration tests using real Redis for concurrency scenarios."""

    def setup_method(self):
        """Clean up Redis before each test."""
        redis_client = get_client()
        # Clean up any test keys
        test_keys = redis_client.keys("duration_quantiles*")
        if test_keys:
            redis_client.delete(*test_keys)

    def teardown_method(self):
        """Clean up Redis after each test."""
        redis_client = get_client()
        test_keys = redis_client.keys("duration_quantiles*")
        if test_keys:
            redis_client.delete(*test_keys)

    def test_concurrent_quantiles_calculation_real_redis(self):
        """Test that concurrent workers get consistent quantiles using real Redis."""
        durations = list(range(100, 1000, 20))  # Realistic data
        hour_bucket = "2024-01-15:14"

        results = []
        errors = []

        def worker_function(worker_id):
            """Simulate a Temporal worker calculating quantiles."""
            try:
                result = get_cached_quantiles_or_calculate(durations, hour_bucket, max_retries=3)
                return worker_id, result
            except Exception as e:
                errors.append(f"Worker {worker_id}: {e}")
                return worker_id, None

        # Simulate 5 workers starting simultaneously
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker_function, i) for i in range(5)]

            for future in as_completed(futures):
                worker_id, result = future.result()
                results.append((worker_id, result))

        # Verify no errors occurred
        assert len(errors) == 0, f"Errors occurred: {errors}"

        # All workers should have gotten a result
        assert len(results) == 5

        # All results should be identical (consistency achieved)
        first_result = results[0][1]
        assert first_result is not None, "First result should not be None"

        for worker_id, result in results:
            assert result is not None, f"Worker {worker_id} got None result"
            assert result == first_result, f"Worker {worker_id} got different result: {result} vs {first_result}"

        # Verify the cache was actually used (should be in Redis now)
        cached_result = get_quantiles(hour_bucket)
        assert cached_result == first_result

    def test_lock_contention_with_real_redis(self):
        """Test lock contention behavior with real Redis operations."""
        hour_bucket = "2024-01-15:15"
        cache_key = _get_cache_key(hour_bucket)
        lock_key = _get_lock_key(hour_bucket)

        redis_client = get_client()

        # Manually acquire the lock to simulate contention
        lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=300)
        assert lock_acquired, "Should be able to acquire lock initially"

        try:
            # Try to store quantiles while lock is held by another process
            test_quantiles = [100.0, 200.0, 300.0]
            result = store_quantiles(test_quantiles, max_value=400, hour_bucket=hour_bucket)

            # Should fail because lock is already held
            assert result is False, "Should fail to store when lock is held"

            # Cache should still be empty
            assert not redis_client.exists(cache_key), "Cache should be empty when store fails"

        finally:
            # Release the lock
            redis_client.delete(lock_key)

        # Now storing should succeed
        result = store_quantiles(test_quantiles, max_value=400, hour_bucket=hour_bucket)
        assert result is True, "Should succeed after lock is released"
        assert redis_client.exists(cache_key), "Cache should exist after successful store"

    def test_cache_expiration_behavior(self):
        """Test that cache expiration works correctly."""
        hour_bucket = "2024-01-15:16"
        test_quantiles = [100.0, 200.0, 300.0]
        test_max = 400

        # Store with short TTL for testing
        redis_client = get_client()
        cache_key = _get_cache_key(hour_bucket)

        # Store quantiles with 1 second TTL
        with patch("posthog.temporal.messaging.quantiles_storage.DEFAULT_TTL", 1):
            result = store_quantiles(test_quantiles, max_value=test_max, hour_bucket=hour_bucket)
            assert result is True

        # Should be retrievable immediately
        cached_result = get_quantiles(hour_bucket)
        assert cached_result == CachedQuantiles(quantiles=test_quantiles, max_value=test_max)

        # Wait for expiration
        time.sleep(1.1)

        # Should be gone now
        cached_result = get_quantiles(hour_bucket)
        assert cached_result is None
        assert not redis_client.exists(cache_key)

    def test_realistic_workflow_simulation(self):
        """Simulate the actual scenario: p0-p50 and p50-p80 workflows starting together."""
        durations = [
            # Simulated cohort durations from database query
            100,
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
            950,
            1000,
            1100,
            1200,
            1300,
            1400,
            1500,
            1600,
            1700,
            1800,
            1900,
            2000,
        ]
        hour_bucket = "2024-01-15:17"

        p0_p50_result = None
        p50_p80_result = None
        errors = []

        def p0_p50_workflow():
            """Simulate p0-p50 workflow calculating quantiles."""
            nonlocal p0_p50_result
            try:
                cached = get_cached_quantiles_or_calculate(durations, hour_bucket)
                if cached:
                    # Calculate p0-p50 thresholds
                    p50_index = 50 - 1  # quantiles[49] is p50
                    p0_p50_result = {"min_threshold_ms": 0, "max_threshold_ms": int(cached.quantiles[p50_index])}
            except Exception as e:
                errors.append(f"p0-p50 workflow error: {e}")

        def p50_p80_workflow():
            """Simulate p50-p80 workflow calculating quantiles."""
            nonlocal p50_p80_result
            try:
                cached = get_cached_quantiles_or_calculate(durations, hour_bucket)
                if cached:
                    # Calculate p50-p80 thresholds
                    p50_index = 50 - 1  # quantiles[49] is p50
                    p80_index = 80 - 1  # quantiles[79] is p80
                    p50_p80_result = {
                        "min_threshold_ms": int(cached.quantiles[p50_index]),
                        "max_threshold_ms": int(cached.quantiles[p80_index]),
                    }
            except Exception as e:
                errors.append(f"p50-p80 workflow error: {e}")

        # Start both workflows simultaneously
        threads = [threading.Thread(target=p0_p50_workflow), threading.Thread(target=p50_p80_workflow)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join(timeout=5)  # 5 second timeout

        # Verify no errors
        assert len(errors) == 0, f"Workflow errors: {errors}"

        # Both workflows should have results
        assert p0_p50_result is not None, "p0-p50 workflow should have result"
        assert p50_p80_result is not None, "p50-p80 workflow should have result"

        # Critical test: No overlapping thresholds (the bug we fixed)
        assert p0_p50_result["max_threshold_ms"] == p50_p80_result["min_threshold_ms"], (
            f"Threshold overlap detected! p0-p50 max: {p0_p50_result['max_threshold_ms']}, "
            f"p50-p80 min: {p50_p80_result['min_threshold_ms']}"
        )

        # Verify logical order
        assert p0_p50_result["min_threshold_ms"] == 0
        assert p0_p50_result["max_threshold_ms"] < p50_p80_result["max_threshold_ms"]

    def test_high_concurrency_stress_test(self):
        """Stress test with many concurrent workers to verify robustness."""
        durations = list(range(50, 500, 5))  # Large dataset
        hour_bucket = "2024-01-15:18"
        num_workers = 10

        results = []
        errors = []

        def stress_worker(worker_id):
            """Worker that tries to get quantiles under high concurrency."""
            try:
                # Add small random delay to increase contention
                time.sleep(0.001 * (worker_id % 3))
                result = get_cached_quantiles_or_calculate(durations, hour_bucket, max_retries=5)
                return worker_id, result, time.time()
            except Exception as e:
                errors.append(f"Worker {worker_id}: {e}")
                return worker_id, None, time.time()

        start_time = time.time()

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(stress_worker, i) for i in range(num_workers)]

            for future in as_completed(futures):
                worker_id, result, finish_time = future.result()
                results.append((worker_id, result, finish_time))

        end_time = time.time()

        # Verify no errors
        assert len(errors) == 0, f"Stress test errors: {errors}"

        # All workers completed successfully
        assert len(results) == num_workers

        # All got same result
        first_result = results[0][1]
        assert first_result is not None

        for worker_id, result, _ in results:
            assert result == first_result, f"Worker {worker_id} got inconsistent result"

        # Test completed in reasonable time (should not be blocked excessively)
        total_time = end_time - start_time
        assert total_time < 10, f"Stress test took too long: {total_time}s"
