import uuid
from collections.abc import Callable

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, RateLimit
from posthog.constants import AvailableFeature


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


class TestOrgConcurrencyLimit(BaseTest):
    """Test the get_org_app_concurrency_limit helper function"""

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_no_org_limit_returns_none(self):
        """Test that get_org_app_concurrency_limit returns None when no org limit is found"""
        from posthog.clickhouse.client.limit import get_org_app_concurrency_limit

        # Mock Redis to return None (cache miss)
        with patch("posthog.clickhouse.client.limit.redis.get_client") as mock_redis:
            mock_redis.return_value.get.return_value = None

            # Call the helper method directly
            result = get_org_app_concurrency_limit(self.organization.id)

            # Should return None since no org-specific limit is configured
            self.assertIsNone(result)

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_org_limit_with_cache_miss_then_hit(self):
        """Test that cache miss hits database, then subsequent calls use cache"""
        from posthog.clickhouse.client.limit import get_org_app_concurrency_limit

        # Set up organization with QUERY_CONCURRENCY feature
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATION_APP_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": 50,
            }
        ]
        self.organization.save()

        # First call: cache miss, should hit database and cache the result
        with patch("posthog.clickhouse.client.limit.redis.get_client") as mock_redis:
            mock_redis.return_value.get.return_value = None
            mock_redis.return_value.setex = Mock()

            result = get_org_app_concurrency_limit(self.organization.id)

            # Should return the org limit
            self.assertEqual(result, 50)
            # Verify that setex was called to cache the result
            mock_redis.return_value.setex.assert_called_once_with(
                f"org_app_concurrency_limit:{self.organization.id}", 3600, 50
            )

        # Second call: cache hit, should not hit database
        with patch("posthog.clickhouse.client.limit.redis.get_client") as mock_redis2:
            mock_redis2.return_value.get.return_value = b"50"

            result2 = get_org_app_concurrency_limit(self.organization.id)

            # Should return cached value
            self.assertEqual(result2, 50)

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_org_limit_with_invalid_limit_values(self):
        """Test that invalid limit values return None"""
        from posthog.clickhouse.client.limit import get_org_app_concurrency_limit

        test_cases = [
            {
                "key": AvailableFeature.ORGANIZATION_APP_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": "not-a-number",
            },
            {
                "key": AvailableFeature.ORGANIZATION_APP_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
                "limit": None,
            },
            {
                "key": AvailableFeature.ORGANIZATION_APP_QUERY_CONCURRENCY_LIMIT,
                "name": "Query Concurrency",
            },  # missing limit
        ]

        with patch("posthog.clickhouse.client.limit.redis.get_client") as mock_redis:
            mock_redis.return_value.get.return_value = None

            for feature_config in test_cases:
                self.organization.available_product_features = [feature_config]
                self.organization.save()

                result = get_org_app_concurrency_limit(self.organization.id)
                self.assertIsNone(result)

    @patch("posthog.clickhouse.client.limit.TEST", False)
    def test_org_limit_exception_handling(self):
        """Test that exceptions are handled gracefully"""
        from posthog.clickhouse.client.limit import get_org_app_concurrency_limit

        # Test with non-existent org
        with patch("posthog.clickhouse.client.limit.redis.get_client") as mock_redis:
            mock_redis.return_value.get.return_value = None

            result = get_org_app_concurrency_limit(uuid.uuid4())  # Non-existent org
            self.assertIsNone(result)
