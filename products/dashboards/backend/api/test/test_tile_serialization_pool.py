import threading
from concurrent.futures import ThreadPoolExecutor

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.clickhouse.client.async_task_chain import add_task_to_on_commit, get_task_chain

from products.dashboards.backend.api.dashboard import collect_tile_futures, serialize_tile_in_worker


class TestTileSerializationPool(SimpleTestCase):
    def test_collect_returns_results_in_submission_order(self):
        def make(i: int) -> tuple[int, dict, list]:
            return (i, {"order": i}, [])

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(make, i) for i in range(4)]
            results, failure = collect_tile_futures(futures, timeout=5)

        assert failure is None
        assert [order for order, _, _ in results] == [0, 1, 2, 3]

    def test_collect_keeps_completed_results_when_one_tile_raises(self):
        boom = ValueError("tile exploded")

        def bad() -> tuple[int, dict, list]:
            raise boom

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(lambda: (0, {}, ["task-a"])), pool.submit(bad)]
            results, failure = collect_tile_futures(futures, timeout=5)

        assert failure is boom
        assert results == [(0, {}, ["task-a"])]

    def test_collect_times_out_and_cancels_unstarted_work(self):
        release = threading.Event()
        started = threading.Event()

        def hang() -> tuple[int, dict, list]:
            started.set()
            release.wait(timeout=10)
            return (0, {}, [])

        with ThreadPoolExecutor(max_workers=1) as pool:
            futures = [pool.submit(hang), pool.submit(lambda: (1, {}, []))]
            assert started.wait(timeout=5)
            results, failure = collect_tile_futures(futures, timeout=0.05)
            release.set()

        assert isinstance(failure, TimeoutError)
        assert results == []
        assert futures[1].cancelled()

    def test_worker_failure_drains_chain_and_fails_orphaned_task_statuses(self):
        manager = MagicMock()
        status = MagicMock()

        def fake_serialize(tile, order, context):
            add_task_to_on_commit(MagicMock(), manager, status)
            raise ValueError("serialization failed")

        with patch("products.dashboards.backend.api.dashboard.serialize_tile_with_context", side_effect=fake_serialize):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(serialize_tile_in_worker, MagicMock(), 0, {}, True)
                with self.assertRaises(ValueError):
                    future.result()

                # Same pool thread serves this next task; its chain must be empty.
                assert pool.submit(get_task_chain).result() == []

        manager.store_query_status.assert_called_once_with(status)
        assert status.error is True
        assert status.complete is True
