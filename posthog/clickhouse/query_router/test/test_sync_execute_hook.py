import json
from types import TracebackType
from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from redis import Redis

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_router.admission import get_query_router
from posthog.clickhouse.query_router.config import (
    Pool,
    PoolBounds,
    QueryClass,
    RouterMode,
    limit_key,
    running_key,
    waiting_key,
    waiting_seen_key,
)
from posthog.clickhouse.query_tagging import tags_context
from posthog.exceptions import ClickHouseAtCapacity
from posthog.redis import get_client

# BACKGROUND may use half the limit, so a limit of 2 is full for it with one query running.
SMALL_LIMIT = 2


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _running_slots(redis: Redis, pool: Pool) -> int:
    return sum(redis.zcard(running_key(pool, query_class)) for query_class in QueryClass)


class _FakeClient:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self.settings: dict[str, Any] | None = None
        self.running_during_execute: int | None = None

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        return None

    def execute(self, query: str, *, settings: dict[str, Any], **kwargs: Any) -> list[tuple[Any, ...]]:
        self.settings = settings
        self.running_during_execute = _running_slots(self._redis, Pool.OFFLINE)
        return []

    def log_comment(self) -> dict[str, Any]:
        assert self.settings is not None
        return json.loads(self.settings["log_comment"])


class TestSyncExecuteQueryRouterHook(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.redis = get_client()
        self.addCleanup(self._delete_router_keys)
        self.clock = _FakeClock()
        router = get_query_router()
        self.enterContext(patch.object(router, "get_time", self.clock.time))
        self.enterContext(patch.object(router, "sleep", self.clock.sleep))
        self.get_global_mode = self._start_patch("get_global_mode", RouterMode.OBSERVE)
        self.get_mode = self._start_patch("get_mode", RouterMode.OBSERVE)
        self._start_patch("get_pool_bounds", PoolBounds(floor=1, ceiling=SMALL_LIMIT))
        self.ch_client = _FakeClient(self.redis)
        self.client_from_pool = self.enterContext(
            patch("posthog.clickhouse.client.execute.get_client_from_pool", return_value=self.ch_client)
        )

    def _start_patch(self, name: str, return_value: object) -> MagicMock:
        return self.enterContext(patch(f"posthog.clickhouse.query_router.config.{name}", return_value=return_value))

    def _delete_router_keys(self) -> None:
        for pool in Pool:
            self.redis.delete(
                *(running_key(pool, query_class) for query_class in QueryClass),
                waiting_key(pool),
                waiting_seen_key(pool),
                limit_key(pool),
            )

    def _enforce_with_a_full_pool(self) -> str:
        self.get_global_mode.return_value = RouterMode.ENFORCE
        self.get_mode.return_value = RouterMode.ENFORCE
        held_key = running_key(Pool.OFFLINE, QueryClass.INTERACTIVE)
        self.redis.zadd(held_key, {"held": (self.clock.now + 3600) * 1000})
        return held_key

    def test_observed_query_holds_a_slot_while_it_runs_and_logs_its_class(self) -> None:
        with tags_context(kind="celery", id="posthog.tasks.example"):
            sync_execute("SELECT 1", flush=False, workload=Workload.OFFLINE, team_id=1)

        assert self.ch_client.running_during_execute == 1
        assert _running_slots(self.redis, Pool.OFFLINE) == 0
        assert self.ch_client.log_comment()["query_router_class"] == "background"

    def test_dropped_query_never_takes_a_clickhouse_connection(self) -> None:
        self._enforce_with_a_full_pool()

        with tags_context(kind="celery", id="posthog.tasks.example"):
            with self.assertRaises(ClickHouseAtCapacity):
                sync_execute("SELECT 1", flush=False, workload=Workload.OFFLINE, team_id=1)

        self.client_from_pool.assert_not_called()

    def test_query_admitted_after_a_wait_logs_the_wait(self) -> None:
        held_key = self._enforce_with_a_full_pool()

        def free_the_pool_and_sleep(seconds: float) -> None:
            self.redis.zrem(held_key, "held")
            self.clock.sleep(seconds)

        self.enterContext(patch.object(get_query_router(), "sleep", free_the_pool_and_sleep))
        with tags_context(kind="celery", id="posthog.tasks.example"):
            sync_execute("SELECT 1", flush=False, workload=Workload.OFFLINE, team_id=1)

        assert self.ch_client.log_comment()["query_router_wait_ms"] > 0

    def test_query_on_an_explicit_client_is_not_routed(self) -> None:
        with tags_context(kind="celery", id="posthog.tasks.example"):
            sync_execute("SELECT 1", flush=False, workload=Workload.OFFLINE, team_id=1, sync_client=self.ch_client)

        assert self.ch_client.running_during_execute == 0
        assert "query_router_class" not in self.ch_client.log_comment()
