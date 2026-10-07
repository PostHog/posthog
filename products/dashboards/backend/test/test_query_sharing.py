import asyncio
from concurrent.futures import CancelledError, ThreadPoolExecutor
from threading import Barrier, Event

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import HogQLQueryResponse

from posthog.hogql.multi_query import SharingQuery
from posthog.hogql.parser import parse_select
from posthog.hogql.query import HogQLQueryExecutor

from products.dashboards.backend.api.query_sharing import DashboardQuerySharingParamsSerializer
from products.dashboards.backend.query_sharing import DashboardQuerySharing
from products.dashboards.backend.query_sharing_stream import DashboardQuerySharingStream


class TestDashboardQuerySharing(SimpleTestCase):
    @staticmethod
    def executor(sql: str, barrier: Barrier | None = None) -> Mock:
        executor = Mock(spec=HogQLQueryExecutor)
        executor.query = sql
        executor.team = Mock()
        executor.context = Mock()
        executor.query_type = "HogQLQuery"
        executor.connection_id = None
        executor.send_raw_query = False
        executor.hogql = sql
        executor.clickhouse_settings = None
        executor.query_modifiers = None
        executor.limit = None
        executor.offset = None
        executor.execute.return_value = HogQLQueryResponse(results=[(7,)], columns=["n"], types=[("n", "UInt64")])

        def prepare(*, query_id: str, scope_key: str) -> SharingQuery:
            if barrier:
                barrier.wait(timeout=10)
            return SharingQuery(query_id=query_id, query=parse_select(sql), context_key=scope_key, sharing_enabled=True)

        executor.prepare_for_sharing.side_effect = prepare
        return executor

    @parameterized.expand([("success", False), ("shared_failure", True)])
    def test_compatible_queries_share_and_fall_back_independently(self, _name: str, fail: bool) -> None:
        sharing = DashboardQuerySharing(match_window_seconds=30)
        barrier = Barrier(2)
        executors = [self.executor("SELECT count() AS n FROM events", barrier) for _ in range(2)]
        shared = Mock()
        shared.execute.side_effect = ValueError("bad shared query") if fail else None
        shared.execute.return_value = HogQLQueryResponse(results=[(7,)], columns=["n"], types=[("n", "UInt64")])
        if fail:
            executors[0].execute.side_effect = ValueError("one bad tile")
        with patch("products.dashboards.backend.query_sharing.HogQLQueryExecutor", return_value=shared):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(sharing.execute, executor) for executor in executors]
                if fail:
                    with self.assertRaisesRegex(ValueError, "one bad tile"):
                        futures[0].result(timeout=10)
                else:
                    self.assertEqual(futures[0].result(timeout=10).results, [(7,)])
                self.assertEqual(futures[1].result(timeout=10).results, [(7,)])
        self.assertEqual(shared.execute.call_count, 1)
        self.assertEqual([executor.execute.call_count for executor in executors], [int(fail), int(fail)])

    def test_unsupported_query_does_not_wait_or_retry_its_error(self) -> None:
        executor = self.executor("SELECT * FROM events")
        executor.execute.side_effect = ValueError("bad tile")
        with self.assertRaisesRegex(ValueError, "bad tile"):
            DashboardQuerySharing(match_window_seconds=30).execute(executor)
        executor.execute.assert_called_once()

    def test_stream_delivers_fast_tile_before_slow_tile(self) -> None:
        release = Event()

        def slow() -> dict:
            if not release.wait(timeout=10):
                raise AssertionError("Slow tile never released")
            return {"type": "tile", "tile": {"id": 1}}

        stream = DashboardQuerySharingStream(
            jobs=[slow, lambda: {"type": "tile", "tile": {"id": 2}}], team_id=1, query_id="test"
        )
        iterator = stream.stream()
        try:
            self.assertIn(b'"id":2', next(iterator))
        finally:
            release.set()
        self.assertIn(b'"id":1', next(iterator))
        self.assertIn(b'"complete"', next(iterator))
        with self.assertRaises(StopIteration):
            next(iterator)

    @parameterized.expand([("sync", False), ("async", True)])
    def test_disconnect_cancels_queries_and_prevents_late_execution(self, _name: str, asynchronous: bool) -> None:
        release = Event()
        finished = Event()
        executor = self.executor("SELECT * FROM events")

        def slow() -> dict:
            try:
                if not release.wait(timeout=10):
                    raise AssertionError("Slow tile never released")
                stream._sharing.execute(executor)
                raise AssertionError("Cancelled tile executed")
            except CancelledError:
                return {"type": "tile", "tile": {"id": 1}}
            finally:
                finished.set()

        stream = DashboardQuerySharingStream(
            jobs=[slow, lambda: {"type": "tile", "tile": {"id": 2}}], team_id=1, query_id="test"
        )

        async def disconnect() -> None:
            iterator = stream.astream()
            self.assertIn(b'"id":2', await anext(iterator))
            await iterator.aclose()

        try:
            with patch("products.dashboards.backend.query_sharing_stream.cancel_query_on_cluster") as cancel:
                if asynchronous:
                    asyncio.run(disconnect())
                else:
                    iterator = stream.stream()
                    self.assertIn(b'"id":2', next(iterator))
                    iterator.close()
                cancel.assert_any_call(team_id=1, client_query_id="test-tile-0-")
        finally:
            release.set()
        self.assertTrue(finished.wait(timeout=10))
        executor.execute.assert_not_called()

    @parameterized.expand(
        [
            ("duplicate", "1,1"),
            ("invalid", "a"),
            ("negative", "-1"),
            ("oversized", ",".join(str(i) for i in range(1, 34))),
        ]
    )
    def test_rejects_invalid_tile_batches(self, _name: str, tile_ids: str) -> None:
        serializer = DashboardQuerySharingParamsSerializer(
            data={"tile_ids": tile_ids, "client_query_id": "00000000-0000-4000-8000-000000000001"}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("tile_ids", serializer.errors)
