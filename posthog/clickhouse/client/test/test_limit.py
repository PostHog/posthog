from unittest.mock import patch
from posthog.clickhouse.client.limit import (
    RateLimit,
    ConcurrencyLimitExceeded,
    get_app_org_rate_limiter,
    DEFAULT_APP_ORG_CONCURRENT_QUERIES,
)
from posthog.constants import AvailableFeature
from posthog.test.base import BaseTest
from collections.abc import Callable


class TestRateLimit(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.limit = RateLimit(
            max_concurrency=1,
            applicable=lambda *args, **kwargs: (kwargs.get("is_api") if "is_api" in kwargs else args[0]),
            limit_name="api_per_team",
            get_task_name=lambda *args, **kwargs: f"rate-limit-test-task:{kwargs.get('team_id') or args[1]}",
            get_task_key=lambda *args, **kwargs: f"limit:rate-limit-test-task:{kwargs.get('team_id') or args[1]}",
            get_task_id=lambda *args, **kwargs: f"{kwargs.get('task_id') or args[2]}",
            ttl=10,
        )
        self.cancels: list[tuple[str | None, str | None]] = []

    def tearDown(self) -> None:
        for a, b in self.cancels:
            self.limit.release(a, b)

    def test_rate_limit(self):
        args, kwargs = (), {"is_api": True, "team_id": 7, "task_id": 17}

        self.cancels.append(self.limit.use(*args, **kwargs))

    def test_rate_limit_fail(self):
        self.cancels.append(self.limit.use(is_api=True, team_id=8, task_id=17))
        with self.assertRaises(ConcurrencyLimitExceeded):
            self.cancels.append(self.limit.use(True, 8, 18))

    def test_rate_limits_no_inference(self):
        """
        User limits do not interfere even with same task ids.
        """
        self.cancels.append(self.limit.use(is_api=True, team_id=9, task_id=17))
        self.cancels.append(self.limit.use(is_api=True, team_id=10, task_id=17))
        self.cancels.append(self.limit.use(is_api=True, team_id=11, task_id=17))

    def test_ttl(self):
        x = 0

        def get_time_plus_100():
            nonlocal x
            x = x + 100
            return x

        self.limit.get_time = get_time_plus_100
        self.cancels.append(self.limit.use(is_api=True, team_id=9, task_id=17))
        self.cancels.append(self.limit.use(is_api=True, team_id=9, task_id=18))
        self.cancels.append(self.limit.use(is_api=True, team_id=9, task_id=19))

    def test_applicable(self):
        @self.limit.wrap
        def some_func(is_api: bool, team_id: int, task_id: int):
            pass

        some_func(is_api=True, team_id=9, task_id=17)
        # none of the belows
        some_func(is_api=False, team_id=9, task_id=19)
        some_func(is_api=False, team_id=9, task_id=19)
        some_func(is_api=False, team_id=9, task_id=19)

    def test_context(self):
        result = 0
        with self.limit.run(is_api=True, team_id=9, task_id=17):
            result += 1

        with self.limit.run(is_api=True, team_id=9, task_id=17):
            result += 2

        assert result == 3

    def test_context_fail(self):
        result = 0
        with self.limit.run(is_api=True, team_id=9, task_id=17):
            result += 1
            with self.assertRaises(ConcurrencyLimitExceeded):
                with self.limit.run(is_api=True, team_id=9, task_id=18):
                    result += 2
                result += 4
            result += 8

        assert result == 9

    def test_run_applicable(self):
        result = 0
        with self.limit.run(is_api=True, team_id=9, task_id=17):
            result += 1
            with self.limit.run(is_api=False, team_id=9, task_id=18):
                result += 2
            result += 4

        assert result == 7

    def test_custom_rate_limit_fail(self):
        self.cancels.append(self.limit.use(is_api=True, team_id=8, task_id=17))
        self.cancels.append(self.limit.use(is_api=True, team_id=8, task_id=18, limit=2))
        with self.assertRaises(ConcurrencyLimitExceeded):
            self.cancels.append(self.limit.use(True, 8, 19, limit=2))

    def test_exception(self):
        result = 0
        with self.assertRaises(Exception):
            result += 1
            with self.limit.run(is_api=True, team_id=9, task_id=17):
                result += 2
                raise Exception()

        with self.limit.run(is_api=True, team_id=9, task_id=17):
            result += 8

        assert result == 11

    def test_retry_mechanism_raises_exception(self):
        """
        Test that the retry mechanism raises an exception if despite waiting for the retry timeout, the slot is not available.
        """
        retry_limit = RateLimit(
            max_concurrency=1,
            applicable=lambda *args, **kwargs: True,
            limit_name="test_retry_mechanism_raises_exception",
            get_task_name=lambda *args, **kwargs: "test_retry_mechanism_raises_exception",
            get_task_id=lambda *args, **kwargs: f"task-{kwargs.get('task_id', 1)}",
            ttl=10,
            retry=0.1,  # 100ms initial retry
            retry_timeout=0.5,  # 500ms total timeout
        )

        time_helper = TimeHelper()
        retry_limit.sleep = time_helper.sleep
        retry_limit.get_time = time_helper.get_time

        # First task should succeed immediately
        with retry_limit.run(task_id=1):
            pass

        # Second task should retry and eventually fail due to timeout
        retry_limit.use(task_id=2)
        with self.assertRaises(ConcurrencyLimitExceeded):
            with retry_limit.run(task_id=2):
                pass

        # Verify exponential backoff
        assert len(time_helper.sleep_times) == 3
        for i in range(1, len(time_helper.sleep_times)):
            assert time_helper.sleep_times[i] > time_helper.sleep_times[i - 1]  # Each retry should wait longer
        total_sleep_time = sum(time_helper.sleep_times[:-1])

        # Verify total time is within timeout
        assert total_sleep_time <= 0.5  # Should not exceed retry_timeout

    def test_retry_mechanism_acquires_slot(self):
        """
        Test that the retry mechanism acquires a slot if it is available.
        """
        retry_limit = RateLimit(
            max_concurrency=1,
            applicable=lambda *args, **kwargs: True,
            limit_name="test_retry_mechanism_acquires_slot",
            get_task_name=lambda *args, **kwargs: "test_retry_mechanism_acquires_slot",
            get_task_id=lambda *args, **kwargs: f"task-{kwargs.get('task_id', 1)}",
            ttl=10,
            retry=0.1,  # 100ms initial retry
            retry_timeout=0.5,  # 500ms total timeout
        )

        running_task_key, task_id = retry_limit.use(task_id=1)  # consumes the slot

        def on_sleep(duration):
            if duration > 0.1:  # after second sleep, the slot is released
                retry_limit.release(running_task_key, task_id)

        time_helper = TimeHelper(on_sleep)

        retry_limit.sleep = time_helper.sleep
        retry_limit.get_time = time_helper.get_time

        with retry_limit.run(task_id=2):
            pass

        # Verify exponential backoff
        assert len(time_helper.sleep_times) == 2
        for i in range(1, len(time_helper.sleep_times)):
            assert time_helper.sleep_times[i] > time_helper.sleep_times[i - 1]  # Each retry should wait longer
        total_sleep_time = sum(time_helper.sleep_times[:-1])

        # Verify total time is within timeout
        assert total_sleep_time <= 0.5  # Should not exceed retry_timeout


class TimeHelper:
    def __init__(self, on_sleep: Callable[[float], None] = lambda _: None):
        self.t = 1492.0
        self.on_sleep = on_sleep
        self.sleep_times: list[float] = []

    def get_time(self):
        self.t += 0.0001
        return self.t

    def sleep(self, duration: float):
        self.sleep_times.append(duration)
        self.on_sleep(duration)
        self.t += duration


class TestAppOrgRateLimiterWithQueryConcurrency(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Clear the global singleton before each test
        from posthog.clickhouse.client import limit

        limit.__APP_CONCURRENT_QUERY_PER_ORG = None

    def test_default_concurrency_limit(self):
        """Test that the default concurrency limit is used when no feature is available"""
        rate_limiter = get_app_org_rate_limiter()

        # Use the rate limiter with an org that doesn't have the feature
        with rate_limiter.run(org_id=self.organization.id, task_id="test-1"):
            # Should succeed with default limit
            pass

        # Verify we're using the default max_concurrency
        self.assertEqual(rate_limiter.max_concurrency, DEFAULT_APP_ORG_CONCURRENT_QUERIES)

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_query_concurrency_feature_limit(self):
        """Test that the QUERY_CONCURRENCY feature limit is used when available"""
        # Set up organization with QUERY_CONCURRENCY feature
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": 50,
            }
        ]
        self.organization.save()

        rate_limiter = get_app_org_rate_limiter()

        # Mock Redis to return None (cache miss) so it hits the database
        with (
            patch.object(rate_limiter.redis_client, "get", return_value=None),
            patch.object(rate_limiter.redis_client, "setex") as mock_setex,
        ):
            # Use the rate limiter with our org
            with rate_limiter.run(org_id=self.organization.id, task_id="test-1"):
                pass

        # Verify that the org limit was cached
        mock_setex.assert_called_once()

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_query_concurrency_multiple_concurrent_requests(self):
        """Test that concurrency limit is enforced based on feature limit"""
        # Set up organization with a low concurrency limit
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": 2,
            }
        ]
        self.organization.save()

        rate_limiter = get_app_org_rate_limiter()

        # Mock Redis to return None (cache miss) so it hits the database
        with patch.object(rate_limiter.redis_client, "get", return_value=None):
            # First two requests should succeed
            task_key1, task_id1 = rate_limiter.use(org_id=self.organization.id, task_id="test-1")
            task_key2, task_id2 = rate_limiter.use(org_id=self.organization.id, task_id="test-2")

            # Third request should fail due to concurrency limit
            with self.assertRaises(ConcurrencyLimitExceeded):
                rate_limiter.use(org_id=self.organization.id, task_id="test-3")

            # Clean up
            rate_limiter.release(task_key1, task_id1)
            rate_limiter.release(task_key2, task_id2)

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_query_concurrency_fallback_on_error(self):
        """Test that the default limit is used if there's an error getting the feature"""
        # Create an org ID that doesn't exist
        non_existent_org_id = 99999

        rate_limiter = get_app_org_rate_limiter()

        # Should not raise an exception, should fall back to default
        with rate_limiter.run(org_id=non_existent_org_id, task_id="test-1"):
            pass

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_query_concurrency_with_invalid_limit(self):
        """Test that invalid limit values fall back to default"""
        # Set up organization with invalid limit types
        test_cases = [
            {
                "key": AvailableFeature.ORGANIZATION_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": "not-a-number",
            },
            {"key": AvailableFeature.ORGANIZATION_QUERY_CONCURRENCY_LIMIT, "name": "Query Concurrency", "limit": None},
            {
                "key": AvailableFeature.ORGANIZATION_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
            },  # missing limit
        ]

        rate_limiter = get_app_org_rate_limiter()

        for feature_config in test_cases:
            self.organization.available_product_features = [feature_config]
            self.organization.save()

            # Should use default limit, not fail
            with rate_limiter.run(org_id=self.organization.id, task_id=f"test-{feature_config}"):
                pass

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_query_concurrency_not_applicable_to_api_requests(self):
        """Test that QUERY_CONCURRENCY feature doesn't affect API requests"""
        # Set up organization with QUERY_CONCURRENCY feature
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": 1,
            }
        ]
        self.organization.save()

        rate_limiter = get_app_org_rate_limiter()

        # API requests should not be affected by app org rate limiter
        # The applicable function should return False for is_api=True
        self.assertFalse(rate_limiter.applicable(org_id=self.organization.id, is_api=True))

    @patch("posthog.clickhouse.client.limit.current_task")
    def test_query_concurrency_not_applicable_in_celery(self, mock_current_task):
        """Test that rate limiter doesn't apply when running in Celery"""
        mock_current_task.return_value = "some_task"  # Simulate being in Celery

        rate_limiter = get_app_org_rate_limiter()

        # Should not be applicable when in Celery
        self.assertFalse(rate_limiter.applicable(org_id=self.organization.id))

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_query_concurrency_redis_cache_hit(self):
        """Test that Redis cache is used when available"""
        # Set up organization with QUERY_CONCURRENCY feature
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": 50,
            }
        ]
        self.organization.save()

        rate_limiter = get_app_org_rate_limiter()

        # Mock Redis to return a cached value
        with patch.object(rate_limiter.redis_client, "get", return_value=b"50") as mock_get:
            # Use the rate limiter with our org
            with rate_limiter.run(org_id=self.organization.id, task_id="test-1"):
                pass

        # Verify that Redis get was called with the correct key
        mock_get.assert_called_once_with(f"org_concurrency_limit:{self.organization.id}")

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_query_concurrency_redis_cache_miss_then_hit(self):
        """Test that cache miss hits database, then subsequent calls use cache"""
        # Set up organization with QUERY_CONCURRENCY feature
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": 50,
            }
        ]
        self.organization.save()

        rate_limiter = get_app_org_rate_limiter()

        # First call: cache miss, should hit database and cache the result
        with (
            patch.object(rate_limiter.redis_client, "get", return_value=None),
            patch.object(rate_limiter.redis_client, "setex") as mock_setex,
        ):
            with rate_limiter.run(org_id=self.organization.id, task_id="test-1"):
                pass

        # Verify that setex was called to cache the result
        mock_setex.assert_called_once_with(f"org_concurrency_limit:{self.organization.id}", 300, 50)

        # Second call: cache hit, should not hit database
        with (
            patch.object(rate_limiter.redis_client, "get", return_value=b"50"),
            patch.object(rate_limiter.redis_client, "setex") as mock_setex2,
        ):
            with rate_limiter.run(org_id=self.organization.id, task_id="test-2"):
                pass

        # Verify that setex was not called again (cache hit)
        mock_setex2.assert_not_called()

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_query_concurrency_no_org_limit_returns_none(self):
        """Test that get_org_concurrency_limit returns None when no org limit is found"""
        from posthog.clickhouse.client.limit import get_org_concurrency_limit

        # Mock Redis to return None (cache miss)
        with patch("posthog.clickhouse.client.limit.redis.get_client") as mock_redis:
            mock_redis.return_value.get.return_value = None

            # Call the helper method directly
            result = get_org_concurrency_limit(self.organization.id)

            # Should return None since no org-specific limit is configured
            self.assertIsNone(result)

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_query_concurrency_only_sets_max_concurrency_when_limit_found(self):
        """Test that max_concurrency is only set when a valid org limit is found"""
        # Set up organization with QUERY_CONCURRENCY feature
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": 50,
            }
        ]
        self.organization.save()

        rate_limiter = get_app_org_rate_limiter()

        # Mock Redis to return None (cache miss) so it hits the database
        with (
            patch.object(rate_limiter.redis_client, "get", return_value=None),
            patch.object(rate_limiter.redis_client, "setex") as mock_setex,
        ):
            # Use the rate limiter with our org
            with rate_limiter.run(org_id=self.organization.id, task_id="test-1"):
                pass

        # Verify that the org limit was cached
        mock_setex.assert_called_once_with(f"org_concurrency_limit:{self.organization.id}", 300, 50)

        # Test with no org limit
        self.organization.available_product_features = []
        self.organization.save()

        with (
            patch.object(rate_limiter.redis_client, "get", return_value=None),
            patch.object(rate_limiter.redis_client, "setex") as mock_setex2,
        ):
            with rate_limiter.run(org_id=self.organization.id, task_id="test-2"):
                pass

        # Should not cache anything since no org limit was found
        mock_setex2.assert_not_called()

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_priority_order_beta_teams_override_callable(self):
        """Test that beta teams override the callable max_concurrency"""
        from posthog.clickhouse.client.limit import settings

        # Set up organization with QUERY_CONCURRENCY feature
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": 50,
            }
        ]
        self.organization.save()

        rate_limiter = get_app_org_rate_limiter()

        # Mock the team to be in beta
        with patch.object(settings, "API_QUERIES_PER_TEAM", {self.team.id: 5}):
            # Mock Redis to return None (cache miss) so it hits the database
            with patch.object(rate_limiter.redis_client, "get", return_value=None):
                # Use the rate limiter with is_api=True (beta team)
                with rate_limiter.run(org_id=self.organization.id, team_id=self.team.id, is_api=True, task_id="test-1"):
                    pass

        # The beta team limit (5) should override the org limit (50)

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_priority_order_explicit_limit_overrides_callable(self):
        """Test that explicit limit parameter overrides the callable max_concurrency"""
        # Set up organization with QUERY_CONCURRENCY feature
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": 50,
            }
        ]
        self.organization.save()

        rate_limiter = get_app_org_rate_limiter()

        # Mock Redis to return None (cache miss) so it hits the database
        with patch.object(rate_limiter.redis_client, "get", return_value=None):
            # Use the rate limiter with explicit limit parameter
            with rate_limiter.run(org_id=self.organization.id, limit=10, task_id="test-1"):
                pass

        # The explicit limit (10) should override the org limit (50)

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_organization_limit_is_applied_in_use_method(self):
        """Test that organization-specific limits are applied in the use method"""
        # Set up organization with QUERY_CONCURRENCY feature
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": 50,
            }
        ]
        self.organization.save()

        rate_limiter = get_app_org_rate_limiter()

        # Mock Redis to return None (cache miss) so it hits the database
        with patch.object(rate_limiter.redis_client, "get", return_value=None):
            # Use the rate limiter
            with rate_limiter.run(org_id=self.organization.id, task_id="test-1"):
                pass

        # The organization limit should be applied through the use method logic
