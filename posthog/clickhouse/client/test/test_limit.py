from posthog.clickhouse.client.limit import RateLimit, ConcurrencyLimitExceeded
from posthog.test.base import BaseTest
from posthog.redis import get_client


class TestRateLimit(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.redis_client = get_client()
        self.limit = RateLimit(
            max_concurrency=1,
            applicable=lambda *args, **kwargs: (kwargs.get("is_api") if "is_api" in kwargs else args[0]),
            limit_name="api_per_team",
            get_task_name=lambda *args, **kwargs: f"rate-limit-test-task:{kwargs.get('team_id') or args[1]}",
            get_task_key=lambda *args, **kwargs: f"limit:rate-limit-test-task:{kwargs.get('team_id') or args[1]}",
            get_task_id=lambda *args, **kwargs: f"{kwargs.get('task_id') or args[2]}",
            ttl=10,
        )
        self.cancels: list[tuple[str, str]] = []

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
