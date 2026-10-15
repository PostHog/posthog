import asyncio
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import aclosing, asynccontextmanager, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

import aiohttp
import pyarrow as pa
import fakeredis
from parameterized import parameterized
from redis.exceptions import RedisError

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.database.database import Database

from posthog.clickhouse.query_router.admission import AdmissionOutcome, QueryRouter
from posthog.clickhouse.query_router.config import Pool, QueryClass, RouterMode, durations_key, running_key, waiting_key
from posthog.clickhouse.query_router.test.fakes import router_settings
from posthog.clickhouse.query_tagging import Feature, Product, QueryTags, tags_context
from posthog.exceptions import ClickHouseAtCapacity
from posthog.models import Organization, Team
from posthog.temporal.common.clickhouse import ClickHouseClient, ClickHouseError, get_client
from posthog.temporal.data_modeling.activities.materialize_view import LOGGER, hogql_table


class TestAsyncAdmission(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.redis = fakeredis.FakeRedis()
        self.router = QueryRouter(redis_client=self.redis)
        patcher = patch("posthog.clickhouse.query_router.config.get_settings", return_value=router_settings(limit=1))
        patcher.start()
        self.addCleanup(patcher.stop)

    def running(self) -> int:
        return self.redis.zcard(running_key(Pool.OFFLINE, QueryClass.BACKGROUND))

    async def test_holds_slot_until_context_closes(self) -> None:
        async with self.router.aadmit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
            self.assertEqual(self.running(), 1)
        self.assertEqual(self.running(), 0)

    async def test_waiting_admission_does_not_block_stream_executor(self) -> None:
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        queued = asyncio.Event()
        original_script = self.router._try_enter_script

        def observe_queue(*args: Any, **kwargs: Any) -> Any:
            result = original_script(*args, **kwargs)
            if self.redis.zcard(waiting_key(Pool.OFFLINE)):
                loop.call_soon_threadsafe(queued.set)
            return result

        self.router._try_enter_script = MagicMock(side_effect=observe_queue)

        async def waiter() -> None:
            async with self.router.aadmit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
                self.fail("Full pool must block the waiter")

        with self.router.admit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
            task = asyncio.create_task(waiter())
            try:
                await asyncio.wait_for(queued.wait(), timeout=5)
                self.assertEqual(await asyncio.wait_for(asyncio.to_thread(lambda: "decoded"), timeout=1), "decoded")
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertEqual(self.running(), 0)
        self.assertEqual(self.redis.zcard(waiting_key(Pool.OFFLINE)), 0)

    @parameterized.expand([("success", False), ("failure", True)])
    async def test_settings_connections_are_closed_before_streaming(self, _name: str, fail: bool) -> None:
        connections: set[int] = set()

        def load_settings() -> Any:
            connections.add(threading.get_ident())
            if fail:
                raise RuntimeError("settings unavailable")
            return router_settings(limit=1)

        def close_connections() -> None:
            connections.discard(threading.get_ident())

        with (
            self.settings(TEST=False),
            patch("posthog.clickhouse.query_router.config.get_settings", side_effect=load_settings),
            patch("posthog.sync.close_old_connections", side_effect=close_connections),
        ):
            error_context = self.assertRaisesRegex(RuntimeError, "settings unavailable") if fail else nullcontext()
            with error_context:
                async with self.router.aadmit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
                    self.assertEqual(connections, set())
            self.assertEqual(connections, set())

    async def test_cancel_during_redis_call_removes_slot_after_call_returns(self) -> None:
        entered = asyncio.Event()
        finish = threading.Event()
        loop = asyncio.get_running_loop()
        original_script = self.router._try_enter_script

        def delayed_script(*args: Any, **kwargs: Any) -> Any:
            loop.call_soon_threadsafe(entered.set)
            finish.wait(timeout=5)
            return original_script(*args, **kwargs)

        self.router._try_enter_script = MagicMock(side_effect=delayed_script)

        async def query() -> None:
            async with self.router.aadmit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
                self.fail("Cancelled query must not execute")

        task = asyncio.create_task(query())
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            task.cancel()
        finally:
            finish.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.running(), 0)
        self.assertEqual(self.redis.zcard(waiting_key(Pool.OFFLINE)), 0)

    @parameterized.expand([("success", False), ("cancelled", True)])
    async def test_http_response_closes_before_slot_released(self, _name: str, cancel: bool) -> None:
        client = ClickHouseClient(query_router_pool=Pool.OFFLINE, max_execution_time=600)
        response = MagicMock(status=200)
        closed = False

        @asynccontextmanager
        async def post(**kwargs: Any) -> AsyncIterator[MagicMock]:
            nonlocal closed
            self.assertEqual(self.running(), 1)
            try:
                yield response
            finally:
                self.assertEqual(self.running(), 1)
                closed = True

        client.session = MagicMock()
        client.session.post = post
        with patch("posthog.temporal.common.clickhouse.get_query_router", return_value=self.router):
            try:
                async with client.apost_query("SELECT 1", query_parameters=None, query_id="test"):
                    self.assertEqual(self.running(), 1)
                    if cancel:
                        raise asyncio.CancelledError()
            except asyncio.CancelledError:
                self.assertTrue(cancel)
        self.assertTrue(closed)
        self.assertEqual(self.running(), 0)

    @parameterized.expand(
        [("off", RouterMode.OFF, AdmissionOutcome.OFF), ("observe", RouterMode.OBSERVE, AdmissionOutcome.WOULD_WAIT)]
    )
    async def test_modes_share_native_pool_without_waiting(
        self, _name: str, mode: RouterMode, expected: AdmissionOutcome
    ) -> None:
        with self.router.admit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
            with patch(
                "posthog.clickhouse.query_router.config.get_settings", return_value=router_settings(mode=mode, limit=1)
            ):
                async with self.router.aadmit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND) as admission:
                    self.assertEqual(admission.outcome, expected)
                    self.assertEqual(self.running(), 1 if mode == RouterMode.OFF else 2)
            self.assertEqual(self.running(), 1)
        self.assertEqual(self.running(), 0)

    async def test_cancelled_waiter_leaves_native_pool_and_queue_intact(self) -> None:
        entered_queue = asyncio.Event()
        loop = asyncio.get_running_loop()
        original_script = self.router._try_enter_script

        def observe_script(*args: Any, **kwargs: Any) -> Any:
            result = original_script(*args, **kwargs)
            if self.redis.zcard(waiting_key(Pool.OFFLINE)):
                loop.call_soon_threadsafe(entered_queue.set)
            return result

        self.router._try_enter_script = MagicMock(side_effect=observe_script)

        async def query() -> None:
            async with self.router.aadmit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
                self.fail("Full native pool must block the async query")

        with self.router.admit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
            task = asyncio.create_task(query())
            try:
                await asyncio.wait_for(entered_queue.wait(), timeout=5)
            finally:
                task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(self.running(), 1)
            self.assertEqual(self.redis.zcard(waiting_key(Pool.OFFLINE)), 0)

    async def test_redis_error_fails_open_and_removes_uncertain_admission(self) -> None:

        original_script = self.router._try_enter_script

        def lost_reply(*args: Any, **kwargs: Any) -> Any:
            original_script(*args, **kwargs)
            raise RedisError("lost reply")

        self.router._try_enter_script = MagicMock(side_effect=lost_reply)
        async with self.router.aadmit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND) as admission:
            self.assertEqual(admission.outcome, AdmissionOutcome.ERROR)
            self.assertEqual(self.running(), 0)
        self.assertEqual(self.running(), 0)

    async def test_repeated_cancellation_does_not_abandon_release(self) -> None:
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        finish = threading.Event()
        loop = asyncio.get_running_loop()
        original_script = self.router._remove_script

        def delayed_release(*args: Any, **kwargs: Any) -> Any:
            loop.call_soon_threadsafe(entered.set)
            finish.wait(timeout=5)
            return original_script(*args, **kwargs)

        self.router._remove_script = MagicMock(side_effect=delayed_release)

        async def query() -> None:
            async with self.router.aadmit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
                cancelled.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(query())
        try:
            await asyncio.wait_for(cancelled.wait(), timeout=5)
            task.cancel()
            await asyncio.wait_for(entered.wait(), timeout=5)
            task.cancel()
        finally:
            finish.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.running(), 0)

    @parameterized.expand(
        [
            ("default", False, None, {}),
            ("custom_url", True, "http://example.com:8123", {}),
        ]
    )
    async def test_factory_preserves_unrouted_clients(
        self, _name: str, enabled: bool, url: str | None, team_settings: dict[str, dict[str, Any]]
    ) -> None:

        with self.settings(CLICKHOUSE_PER_TEAM_SETTINGS=team_settings):
            async with get_client(team_id=123, clickhouse_url=url, query_router_enabled=enabled) as client:
                self.assertIsNone(client.query_router_pool)
                self.assertNotIn("query_router_enabled", client.params)
                self.assertNotIn("query_router_pool", client.params)

    @parameterized.expand([("complete",), ("consumer_stops",), ("consumer_fails",)])
    async def test_arrow_stream_holds_exactly_one_slot_through_consumption(self, outcome: str) -> None:

        client = ClickHouseClient(query_router_pool=Pool.OFFLINE, max_execution_time=600)
        batch = pa.record_batch({"value": [1, 2]})
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, batch.schema) as writer:
            writer.write_batch(batch)
            writer.write_batch(batch)
        response = MagicMock(status=200)
        response.content.readchunk = AsyncMock(return_value=(sink.getvalue().to_pybytes(), True))
        closed = False

        @asynccontextmanager
        async def post(**kwargs: Any) -> AsyncIterator[MagicMock]:
            nonlocal closed
            self.assertEqual(self.running(), 1)
            try:
                yield response
            finally:
                self.assertEqual(self.running(), 1)
                closed = True

        client.session = MagicMock()
        client.session.post = post
        with patch("posthog.temporal.common.clickhouse.get_query_router", return_value=self.router):
            error_context = (
                self.assertRaisesRegex(ValueError, "sink failed") if outcome == "consumer_fails" else nullcontext()
            )
            with error_context:
                async with aclosing(client.astream_query_as_arrow("SELECT 1 FORMAT ArrowStream")) as stream:
                    count = 0
                    async for result in stream:
                        self.assertTrue(result.equals(batch))
                        self.assertEqual(self.running(), 1)
                        self.assertFalse(closed)
                        count += 1
                        if outcome == "consumer_fails":
                            raise ValueError("sink failed")
                        if outcome == "consumer_stops":
                            break
            self.assertEqual(count, 2 if outcome == "complete" else 1)
        self.assertTrue(closed)
        self.assertEqual(self.running(), 0)

    @parameterized.expand(
        [("early_close",), ("consumer_failure",), ("cancelled",), ("repeated_cancellation",), ("before_headers",)]
    )
    async def test_abandoned_http_query_is_cancelled_before_admission_release(self, outcome: str) -> None:
        password_file = Path(self.enterContext(TemporaryDirectory())) / "token"
        password_file.write_text("synthetic-original")
        client = ClickHouseClient(
            query_router_pool=Pool.OFFLINE,
            user="warehouse-test",
            password="synthetic-password",
            password_file=str(password_file),
        )
        response = MagicMock(status=200)
        response.content.is_eof.return_value = False
        cleanup_started = asyncio.Event()
        finish_cleanup = asyncio.Event()
        query_ids: list[str] = []
        cleanup_clients: list[ClickHouseClient] = []

        @asynccontextmanager
        async def post(**kwargs: Any) -> AsyncIterator[MagicMock]:
            query_ids.append(kwargs["params"].get("query_id"))
            password_file.write_text("synthetic-rotated")
            if outcome == "before_headers":
                raise asyncio.CancelledError()
            yield response

        async def cancel(cancellation_client: ClickHouseClient, query_id: str, *, wait: bool = False) -> None:
            cleanup_clients.append(cancellation_client)
            self.assertEqual(self.running(), 1)
            self.assertEqual(query_id, query_ids[0])
            self.assertTrue(wait)
            self.assertIsNone(cancellation_client.query_router_pool)
            self.assertEqual(cancellation_client._request_headers()["X-ClickHouse-User"], "warehouse-test")
            self.assertEqual(cancellation_client._credentials.password_file, str(password_file))
            self.assertEqual(cancellation_client._request_headers()["X-ClickHouse-Key"], "synthetic-rotated")
            cleanup_started.set()
            await finish_cleanup.wait()

        async def query() -> None:
            async with client.apost_query("SELECT 1", query_parameters=None, query_id=None):
                if outcome in ("cancelled", "repeated_cancellation"):
                    raise asyncio.CancelledError()
                if outcome == "consumer_failure":
                    raise ValueError("sink failed")

        client.session = MagicMock()
        client.session.post = post
        with (
            patch("posthog.temporal.common.clickhouse.get_query_router", return_value=self.router),
            patch.object(ClickHouseClient, "acancel_query", autospec=True, side_effect=cancel),
        ):
            task = asyncio.create_task(query())
            try:
                await asyncio.wait_for(cleanup_started.wait(), timeout=1)
                self.assertIsNotNone(query_ids[0])
                self.assertEqual(self.running(), 1)
                if outcome == "repeated_cancellation":
                    task.cancel()
                    await asyncio.sleep(0)
                    task.cancel()
                self.assertFalse(task.done())
            finally:
                finish_cleanup.set()
            error_context = (
                self.assertRaises(asyncio.CancelledError)
                if outcome in ("cancelled", "repeated_cancellation", "before_headers")
                else self.assertRaisesRegex(ValueError, "sink failed")
                if outcome == "consumer_failure"
                else nullcontext()
            )
            with error_context:
                await task
        self.assertEqual(len(cleanup_clients), 1)
        self.assertEqual(self.running(), 0)

    @parameterized.expand([("timeout", TimeoutError()), ("server_failure", ClickHouseError("kill unavailable"))])
    async def test_failed_cancellation_leaves_unrenewed_slot_to_expire(self, _name: str, error: Exception) -> None:
        client = ClickHouseClient(query_router_pool=Pool.OFFLINE)
        response = MagicMock(status=200)
        response.content.is_eof.return_value = False

        @asynccontextmanager
        async def post(**kwargs: Any) -> AsyncIterator[MagicMock]:
            yield response

        async def cancel(*args: Any, **kwargs: Any) -> None:
            if isinstance(error, TimeoutError):
                await asyncio.Event().wait()
            raise error

        client.session = MagicMock()
        client.session.post = post
        with (
            patch("posthog.temporal.common.clickhouse.get_query_router", return_value=self.router),
            patch("posthog.temporal.common.clickhouse._QUERY_ROUTER_CANCEL_TIMEOUT_SECONDS", 0.01),
            patch.object(ClickHouseClient, "acancel_query", side_effect=cancel),
        ):
            async with client.apost_query("SELECT 1", query_parameters=None, query_id="failed-cancellation"):
                original_slots = self.redis.zrange(
                    running_key(Pool.OFFLINE, QueryClass.BACKGROUND), 0, -1, withscores=True
                )
        self.assertEqual(self.running(), 1)
        await asyncio.to_thread(self.router.renew_slots)
        self.assertEqual(
            self.redis.zrange(running_key(Pool.OFFLINE, QueryClass.BACKGROUND), 0, -1, withscores=True), original_slots
        )

    async def test_synchronous_cancellation_reads_and_checks_server_acknowledgement(self) -> None:
        client = ClickHouseClient()
        response = MagicMock(status=200)
        response.text = AsyncMock(return_value='{"status":0,"num_hosts_remaining":0}\n')

        @asynccontextmanager
        async def post(**kwargs: Any) -> AsyncIterator[MagicMock]:
            self.assertIn(b"SYNC", kwargs["data"])
            self.assertIn(b"JSONEachRow", kwargs["data"])
            yield response

        client.session = MagicMock()
        client.session.post = post
        await client.acancel_query("query-to-cancel", wait=True)
        response.text.assert_awaited_once()
        response.text.return_value = '{"status":1,"num_hosts_remaining":0}\n'
        with self.assertRaises(ClickHouseError):
            await client.acancel_query("query-to-cancel", wait=True)

    async def test_release_failure_stops_renewing_and_expires(self) -> None:

        self.router.get_time = lambda: 1000
        self.enterContext(patch("time.time", side_effect=lambda: self.router.get_time()))
        async with self.router.aadmit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
            slots = self.redis.zrange(running_key(Pool.OFFLINE, QueryClass.BACKGROUND), 0, -1, withscores=True)
            self.assertEqual(slots[0][1], 1_060_000)
            original_script = self.router._remove_script
            self.router._remove_script = MagicMock(side_effect=RedisError("release unavailable"))
        self.assertEqual(self.running(), 1)
        self.router.get_time = lambda: 1040
        await asyncio.to_thread(self.router.renew_slots)
        slots = self.redis.zrange(running_key(Pool.OFFLINE, QueryClass.BACKGROUND), 0, -1, withscores=True)
        self.assertEqual(slots[0][1], 1_060_000)
        self.router._remove_script = original_script
        self.router.get_time = lambda: 1061
        async with self.router.aadmit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
            self.assertEqual(self.running(), 1)
        self.assertEqual(self.running(), 0)

    async def test_refused_query_does_not_send_http_request(self) -> None:

        client = ClickHouseClient(query_router_pool=Pool.OFFLINE)
        client.session = MagicMock()
        self.redis.rpush(durations_key(Pool.OFFLINE), 9000)
        with self.router.admit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
            with patch("posthog.temporal.common.clickhouse.get_query_router", return_value=self.router):
                with self.assertRaises(ClickHouseAtCapacity):
                    async with client.apost_query("SELECT 1", query_parameters=None, query_id="capacity-test"):
                        self.fail("Rejected query must not execute")
            client.session.post.assert_not_called()
            self.assertEqual(self.running(), 1)
            self.assertEqual(self.redis.zcard(waiting_key(Pool.OFFLINE)), 0)

    async def test_live_stream_lease_is_renewed_until_release(self) -> None:
        self.router.get_time = lambda: 1000
        self.enterContext(patch("time.time", side_effect=lambda: self.router.get_time()))
        async with self.router.aadmit(pool=Pool.OFFLINE, query_class=QueryClass.BACKGROUND):
            self.router.get_time = lambda: 1040
            await asyncio.to_thread(self.router.renew_slots)
            slots = self.redis.zrange(running_key(Pool.OFFLINE, QueryClass.BACKGROUND), 0, -1, withscores=True)
            self.assertEqual(slots[0][1], 1_100_000)
        self.router.get_time = lambda: 1080
        await asyncio.to_thread(self.router.renew_slots)
        self.assertEqual(self.running(), 0)

    @parameterized.expand([("shared", {}), ("native_team_override", {"123": {}})])
    async def test_warehouse_factory_routes_stream_as_background_on_shared_offline_pool(
        self, _name: str, team_settings: dict[str, dict[str, Any]]
    ) -> None:

        @asynccontextmanager
        async def post(**kwargs: Any) -> AsyncIterator[MagicMock]:
            tags = QueryTags.model_validate_json(kwargs["params"]["log_comment"])
            self.assertEqual(tags.product, Product.WAREHOUSE)
            self.assertEqual(tags.feature, Feature.DATA_MODELING)
            self.assertEqual(tags.query_router_class, "background")
            self.assertEqual(self.running(), 1)
            self.assertEqual(self.redis.zcard(running_key(Pool.ONLINE, QueryClass.BACKGROUND)), 0)
            yield MagicMock(status=200)

        with (
            self.settings(CLICKHOUSE_PER_TEAM_SETTINGS=team_settings),
            tags_context(team_id=123, product=Product.WAREHOUSE, feature=Feature.DATA_MODELING),
            patch("posthog.temporal.common.clickhouse.get_query_router", return_value=self.router),
        ):
            async with get_client(team_id=123, query_router_enabled=True) as client:
                self.assertEqual(client.query_router_pool, Pool.OFFLINE)
                self.assertEqual(client.query_router_team_id, 123)
                with patch.object(client.session, "post", side_effect=post):
                    async with client.apost_query("SELECT 1", query_parameters=None, query_id="warehouse-test"):
                        self.assertEqual(self.running(), 1)
        self.assertEqual(self.running(), 0)

    async def test_materialization_closes_admitted_stream_when_consumer_fails(self) -> None:

        team = Team(id=123, organization=Organization())
        batch = pa.record_batch({"id": [1]})
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, batch.schema) as writer:
            writer.write_batch(batch)
            writer.write_batch(batch)
        stream_closed = False
        request_slots: list[int] = []

        @asynccontextmanager
        async def post(**kwargs: Any) -> AsyncIterator[MagicMock]:
            nonlocal stream_closed
            response = MagicMock(status=200)
            request_slots.append(self.running())
            if kwargs["data"].startswith(b"DESCRIBE TABLE"):
                response.content.read = AsyncMock(return_value=b"id\tInt64\n")
                yield response
            else:
                tags = QueryTags.model_validate_json(kwargs["params"]["log_comment"])
                self.assertEqual(tags.query_router_class, "background")
                response.content.readchunk = AsyncMock(return_value=(sink.getvalue().to_pybytes(), True))
                try:
                    yield response
                finally:
                    self.assertEqual(self.running(), 1)
                    stream_closed = True

        with (
            tags_context(team_id=team.pk, product=Product.WAREHOUSE, feature=Feature.DATA_MODELING),
            patch("posthog.temporal.common.clickhouse.get_query_router", return_value=self.router),
            patch.object(aiohttp.ClientSession, "post", side_effect=post),
            patch.object(Database, "create_for", return_value=Database()),
            patch(
                "posthog.temporal.data_modeling.activities.materialize_view.create_default_modifiers_for_team",
                return_value=HogQLQueryModifiers(),
            ),
            patch("posthog.temporal.data_modeling.activities.materialize_view.MB_100_IN_BYTES", 1),
            self.assertRaisesRegex(ValueError, "write failed"),
        ):
            async with aclosing(hogql_table("SELECT 1 AS id", team, LOGGER.bind())) as batches:
                async for result, column_types in batches:
                    self.assertTrue(result.equals(batch))
                    self.assertEqual(column_types, [("id", "Int64")])
                    self.assertEqual(self.running(), 1)
                    raise ValueError("write failed")
        self.assertEqual(request_slots, [0, 1])
        self.assertTrue(stream_closed)
        self.assertEqual(self.running(), 0)
