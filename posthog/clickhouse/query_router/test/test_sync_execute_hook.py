import json
import uuid
from contextlib import nullcontext
from types import TracebackType
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from prometheus_client import REGISTRY
from redis import Redis

from posthog.schema import QueryStatus

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.client.execute_async import QueryStatusManager, cancel_query
from posthog.clickhouse.query_router.admission import get_query_router
from posthog.clickhouse.query_router.config import (
    Pool,
    QueryClass,
    RouterMode,
    arrivals_key,
    durations_key,
    running_key,
    waiting_key,
    waiting_seen_key,
)
from posthog.clickhouse.query_router.test.fakes import FakeClock, router_settings
from posthog.clickhouse.query_tagging import AccessMethod, tags_context
from posthog.errors import CHQueryErrorQueryWasCancelled
from posthog.exceptions import ClickHouseAtCapacity
from posthog.redis import get_client

# One held slot fills the pool.
SMALL_LIMIT = 1


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
        self.clock = FakeClock()
        router = get_query_router()
        self.enterContext(patch.object(router, "get_time", self.clock.time))
        self.enterContext(patch.object(router, "sleep", self.clock.sleep))
        self.get_settings = self.enterContext(
            patch(
                "posthog.clickhouse.query_router.config.get_settings",
                return_value=router_settings(mode=RouterMode.OBSERVE, limit=SMALL_LIMIT),
            )
        )
        self.ch_client = _FakeClient(self.redis)
        self.client_from_pool = self.enterContext(
            patch("posthog.clickhouse.client.execute.get_client_from_pool", return_value=self.ch_client)
        )

    def _delete_router_keys(self) -> None:
        for pool in Pool:
            self.redis.delete(
                *(running_key(pool, query_class) for query_class in QueryClass),
                waiting_key(pool),
                waiting_seen_key(pool),
                durations_key(pool),
                arrivals_key(pool),
            )

    def _enforce_with_a_full_pool(self) -> str:
        self.get_settings.return_value = router_settings(mode=RouterMode.ENFORCE, limit=SMALL_LIMIT)
        held_key = running_key(Pool.OFFLINE, QueryClass.INTERACTIVE)
        self.redis.zadd(held_key, {"held": (self.clock.now + 3600) * 1000})
        return held_key

    def test_observed_query_holds_a_slot_while_it_runs_and_logs_its_class(self) -> None:
        with tags_context(kind="celery", id="posthog.tasks.example"):
            sync_execute("SELECT 1", flush=False, workload=Workload.OFFLINE, team_id=1)

        assert self.ch_client.running_during_execute == 1
        assert _running_slots(self.redis, Pool.OFFLINE) == 0
        assert self.ch_client.log_comment()["query_router_class"] == "background"

    def test_dropped_query_is_counted_for_its_team_and_takes_no_clickhouse_connection(self) -> None:
        self._enforce_with_a_full_pool()
        drops = ("posthog_query_router_drops_total", {"pool": "offline", "query_class": "background", "team_id": "1"})
        drops_before = REGISTRY.get_sample_value(*drops) or 0.0

        with tags_context(kind="celery", id="posthog.tasks.example"):
            with self.assertRaises(ClickHouseAtCapacity):
                sync_execute("SELECT 1", flush=False, workload=Workload.OFFLINE, team_id=1)

        self.client_from_pool.assert_not_called()
        assert REGISTRY.get_sample_value(*drops) == drops_before + 1

    def test_query_admitted_after_a_wait_logs_the_wait(self) -> None:
        # A finished query of half a second shows the pool freeing its slot soon enough for the next query to
        # wait instead of being dropped.
        self.redis.lpush(durations_key(Pool.OFFLINE), 500)
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

    @parameterized.expand(
        [("slot_freed", True, True), ("pool_still_full", False, True), ("previous_run_cancelled", True, False)]
    )
    def test_waiter_honors_cancellation_only_for_its_own_run(
        self, _name: str, free_slot: bool, cancel_current_run: bool
    ) -> None:
        held_key = self._enforce_with_a_full_pool()
        self.redis.lpush(durations_key(Pool.OFFLINE), 500)
        query_id = uuid.uuid4().hex
        task_id = uuid.uuid4()
        manager = QueryStatusManager(query_id, 1)
        manager.store_query_status(QueryStatus(id=query_id, team_id=1, task_id=str(task_id)))

        def cancel_while_waiting(seconds: float) -> None:
            cancel_query(1, query_id)
            if free_slot:
                self.redis.zrem(held_key, "held")
            self.clock.sleep(seconds)

        with (
            patch.object(get_query_router(), "sleep", cancel_while_waiting),
            patch("posthog.clickhouse.cancel.cancel_query_on_cluster"),
            patch("posthog.clickhouse.client.execute_async.celery.app.control.revoke"),
            tags_context(
                kind="celery",
                id="posthog.tasks.tasks.process_query_task",
                access_method=AccessMethod.PERSONAL_API_KEY,
                client_query_id=query_id,
                celery_task_id=task_id if cancel_current_run else uuid.uuid4(),
            ),
            self.assertRaises(CHQueryErrorQueryWasCancelled) if cancel_current_run else nullcontext(),
        ):
            sync_execute("SELECT 1", flush=False, workload=Workload.OFFLINE, team_id=1)

        assert self.client_from_pool.call_count == (0 if cancel_current_run else 1)
        assert _running_slots(self.redis, Pool.OFFLINE) == (0 if free_slot else 1)
        assert self.redis.zcard(waiting_key(Pool.OFFLINE)) == 0
        assert self.redis.zcard(waiting_seen_key(Pool.OFFLINE)) == 0
