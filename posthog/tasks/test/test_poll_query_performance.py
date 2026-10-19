import json
from threading import Event

from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

import posthog.tasks.tasks
from posthog.clickhouse.native_metadata import metadata_connection
from posthog.clickhouse.workload import Workload
from posthog.redis import get_client
from posthog.settings import CLICKHOUSE_HOST
from posthog.tasks.poll_query_performance import poll_query_performance, query_manager_from_initial_query_id
from posthog.tasks.tasks import Polling


class TestPollQueryPerformance(SimpleTestCase):
    def setUp(self) -> None:
        patcher = patch(
            "posthog.models.event.new_events_schema.get_instance_setting",
            side_effect=lambda key: getattr(settings, "CLICKHOUSE_NATIVE_EVENTS_HOST", ""),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        def run(payload: str, _deadline: float) -> object:
            job = json.loads(payload)
            return posthog.tasks.poll_query_performance.sync_execute(
                job["sql"],
                {"cluster": job["cluster"]},
                workload=Workload.DEFAULT if job["connection"]["host"] == "native.example.com" else Workload.ONLINE,
            )

        worker = patch("posthog.clickhouse.native_metadata._run_metadata_process", side_effect=run)
        worker.start()
        self.addCleanup(worker.stop)

    @override_settings(CLICKHOUSE_OFFLINE_CLUSTER_HOST="offline.example.com")
    def test_legacy_probe_stays_on_online_host_when_celery_defaults_to_offline(self) -> None:
        with (
            patch("posthog.clickhouse.client.connection._default_workload", Workload.OFFLINE),
        ):
            connection = metadata_connection(polling=True)
        self.assertEqual(connection["host"], CLICKHOUSE_HOST)

    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_healthy_native_progress_survives_stalled_legacy_probe(self) -> None:
        legacy_started, release_legacy, legacy_finished = Event(), Event(), Event()
        native_id = "44_550e8400-e29b-41d4-a716-446655440002_example"

        def execute(
            _query: str, _parameters: dict[str, str], **kwargs: object
        ) -> list[tuple[str, int, int, int, int, int, str]]:
            if kwargs.get("workload") == Workload.ONLINE:
                legacy_started.set()
                try:
                    self.assertTrue(release_legacy.wait(2))
                    raise TimeoutError("legacy unavailable")
                finally:
                    legacy_finished.set()
            return [(native_id, 2, 3, 4, 5, 6, "native-query")]

        with (
            patch("posthog.tasks.poll_query_performance.sync_execute", side_effect=execute),
            patch("posthog.tasks.poll_query_performance.QueryStatusManager") as manager,
            patch(
                "posthog.tasks.poll_query_performance.perf_counter",
                side_effect=lambda: 10.1 if legacy_finished.is_set() else 0,
            ),
            patch("posthog.tasks.poll_query_performance._LEGACY_POLL_TIMEOUT_SECONDS", 0.05, create=True),
        ):
            try:
                poll_query_performance()
                self.assertTrue(legacy_started.is_set())
                manager.return_value.update_clickhouse_query_progresses.assert_called()
            finally:
                release_legacy.set()
                self.assertTrue(legacy_finished.wait(1))

    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_native_wall_deadline_accounts_for_legacy_time_and_preserves_progress(self) -> None:
        release_native, native_started, native_finished = Event(), Event(), Event()
        legacy_id = "44_550e8400-e29b-41d4-a716-446655440001_example"

        def execute(
            _query: str, _parameters: dict[str, str], **kwargs: object
        ) -> list[tuple[str, int, int, int, int, int, str]]:
            if kwargs.get("workload") != Workload.ONLINE:
                native_started.set()
                try:
                    self.assertTrue(release_native.wait(2))
                    return []
                finally:
                    native_finished.set()
            return [(legacy_id, 2, 3, 4, 5, 6, "example-query")]

        with (
            patch("posthog.tasks.poll_query_performance.perf_counter", side_effect=[0, 8.9]),
            patch("posthog.tasks.poll_query_performance.sync_execute", side_effect=execute),
            patch("posthog.tasks.poll_query_performance.QueryStatusManager") as manager,
        ):
            try:
                poll_query_performance()
                self.assertTrue(native_started.is_set())
                manager.return_value.update_clickhouse_query_progresses.assert_called_once()
                self.assertFalse(native_finished.is_set())
            finally:
                release_native.set()
                self.assertTrue(native_finished.wait(1))

    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_native_progress_keeps_legacy_children_of_the_same_query(self) -> None:
        initial_id = "44_550e8400-e29b-41d4-a716-446655440001_example"

        def execute(
            _query: str, _parameters: dict[str, str], **kwargs: object
        ) -> list[tuple[str, int, int, int, int, int, str]]:
            query_id = "native-child" if kwargs.get("workload") != Workload.ONLINE else "legacy-child"
            return [(initial_id, 2, 3, 4, 5, 6, query_id)]

        with (
            patch("posthog.tasks.poll_query_performance.sync_execute", side_effect=execute),
            patch("posthog.tasks.poll_query_performance.QueryStatusManager") as manager,
        ):
            poll_query_performance()
        latest = manager.return_value.update_clickhouse_query_progresses.call_args.args[0]
        self.assertEqual({row["query_id"] for row in latest}, {"legacy-child", "native-child"})

    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_native_progress_survives_legacy_publication_exhausting_the_budget(self) -> None:
        legacy_id = "44_550e8400-e29b-41d4-a716-446655440001_example"
        native_id = "44_550e8400-e29b-41d4-a716-446655440002_example"
        native_finished = Event()
        published_legacy = False

        def execute(_query: str, _parameters: dict[str, str], **kwargs: object) -> list[tuple]:
            if kwargs.get("workload") != Workload.ONLINE:
                native_finished.set()
                return [(native_id, 2, 3, 4, 5, 6, "native-query")]
            return [(legacy_id, 2, 3, 4, 5, 6, "legacy-query")]

        def publish(_progress: object) -> None:
            nonlocal published_legacy
            self.assertTrue(native_finished.wait(1))
            published_legacy = True

        with (
            patch("posthog.tasks.poll_query_performance.sync_execute", side_effect=execute),
            patch("posthog.tasks.poll_query_performance.QueryStatusManager") as manager,
            patch(
                "posthog.tasks.poll_query_performance.perf_counter", side_effect=lambda: 10 if published_legacy else 0
            ),
        ):
            manager.return_value.update_clickhouse_query_progresses.side_effect = publish
            poll_query_performance()
        self.assertEqual(manager.call_count, 2)
        self.assertEqual({call.args[0] for call in manager.call_args_list}, {legacy_id[3:-8], native_id[3:-8]})

    @parameterized.expand([(None,), ("legacy",), ("native",), ("settings",)])
    @override_settings(CLICKHOUSE_NATIVE_EVENTS_HOST="native.example.com")
    def test_progress_includes_native_queries_and_survives_one_unavailable_cluster(self, failed: str | None) -> None:
        legacy_id = "44_550e8400-e29b-41d4-a716-446655440001_example"
        native_id = "44_550e8400-e29b-41d4-a716-446655440002_example"

        def execute(
            _query: str, _parameters: dict[str, str], **kwargs: object
        ) -> list[tuple[str, int, int, int, int, int, str]]:
            native = kwargs.get("workload") != Workload.ONLINE
            if failed == ("native" if native else "legacy"):
                raise RuntimeError("cluster unavailable")
            return [(native_id if native else legacy_id, 2, 3, 4, 5, 6, "example-query")]

        with (
            patch("posthog.tasks.poll_query_performance.sync_execute", side_effect=execute),
            patch("posthog.tasks.poll_query_performance.QueryStatusManager") as manager,
        ):
            if failed == "settings":
                with patch(
                    "posthog.tasks.poll_query_performance.get_new_events_cluster_host",
                    side_effect=RuntimeError("settings unavailable"),
                ):
                    poll_query_performance()
            else:
                poll_query_performance()
        self.assertEqual(manager.call_count, 1 if failed else 2)
        query_ids = {call.args[0] for call in manager.call_args_list}
        if failed != "legacy":
            self.assertIn("550e8400-e29b-41d4-a716-446655440001", query_ids)
        if failed not in ("native", "settings"):
            self.assertIn("550e8400-e29b-41d4-a716-446655440002", query_ids)

    def test_query_manager_from_initial_query_id_succeeds(self) -> None:
        self.assertIsNotNone(query_manager_from_initial_query_id("1_00008400-e29b-41d4-a716-446655440000_fwefwef"))
        self.assertIsNotNone(query_manager_from_initial_query_id("123123_550e8400-e29b-41d4-a716-446655440000_fwefwef"))

    def test_query_manager_from_initial_query_id_fails(self) -> None:
        self.assertIsNone(query_manager_from_initial_query_id("550e8400-e29b-41d4-a716-446655440000"))
        self.assertIsNone(query_manager_from_initial_query_id("fewf_550e8400-e29b-41d4-a716-446655440000_fwefwef"))
        self.assertIsNone(query_manager_from_initial_query_id("1a_550e8400-e29b-41d4-a716-446655440000_fwefwef"))

    @patch("posthog.tasks.poll_query_performance.QueryStatusManager")
    @patch("posthog.tasks.poll_query_performance.sync_execute")
    def test_writes_to_redis_correctly(self, mock_sync_execute: MagicMock, mock_QueryStatusManager: MagicMock) -> None:
        bytes_read = 111
        rows_read = 222
        total_rows_approx = 333
        time_elapsed = 4.301284
        millisecond_cpu_time = 3321332424
        mock_sync_execute.return_value = [
            ("None_None_tHrh4Ox9", 0, 0, 0, 0.002112, 0, "query_id"),
            (
                "12345_550e8400-e29b-41d4-a716-446655440000_eO290UUI",
                rows_read,
                bytes_read,
                total_rows_approx,
                time_elapsed,
                millisecond_cpu_time,
                "550e8400-e29b-41d4-a716-446655440001",
            ),
        ]
        mock_manager = mock_QueryStatusManager.return_value

        poll_query_performance()

        mock_sync_execute.assert_called_once()
        mock_QueryStatusManager.assert_called_once_with("550e8400-e29b-41d4-a716-446655440000", 12345)
        mock_manager.update_clickhouse_query_progresses.assert_called_once_with(
            [
                {
                    "initial_query_id": "12345_550e8400-e29b-41d4-a716-446655440000_eO290UUI",
                    "query_id": "550e8400-e29b-41d4-a716-446655440001",
                    "bytes_read": bytes_read,
                    "rows_read": rows_read,
                    "estimated_rows_total": total_rows_approx,
                    "time_elapsed": int(time_elapsed),
                    "active_cpu_time": millisecond_cpu_time,
                },
            ]
        )


class TestPollQueryPerformanceTask(SimpleTestCase):
    @patch("posthog.tasks.tasks.logger.error")
    def test_poll_query_performance_does_not_run_if_last_update_does_not_match(
        self, mock_logger_error: MagicMock
    ) -> None:
        redis_client = get_client()
        redis_client.set(Polling._SINGLETON_REDIS_KEY, "NOT RIGHT")
        posthog.tasks.tasks.poll_query_performance("DIFFERENT TIME")
        mock_logger_error.assert_called_once_with("Poll query performance task terminating: another poller is running")

    # Mock the inner ClickHouse-querying function: these tests exercise the task wrapper's
    # timing/scheduling logic, not the query. Without this the wrapper runs a real query against a
    # ClickHouse test database that this SimpleTestCase never sets up, so the call raises, gets
    # logged, and the logging consumes a value from the fixed-length `time.time_ns` side_effect —
    # exhausting it and surfacing as StopIteration under --reruns.
    @patch("posthog.tasks.poll_query_performance.poll_query_performance")
    @patch("posthog.tasks.tasks.logger.error")
    @patch("posthog.tasks.tasks.poll_query_performance.apply_async")
    def test_poll_query_performance_runs_and_restarts_itself_with_delay(
        self, mock_apply_async: MagicMock, mock_logger_error: MagicMock, mock_poll_query_performance_nontask: MagicMock
    ) -> None:
        redis_client = get_client()
        key = 1234
        redis_client.set(Polling._SINGLETON_REDIS_KEY, Polling._encode_redis_key(key))
        posthog.tasks.tasks.poll_query_performance(key)

        mock_logger_error.assert_not_called()
        mock_apply_async.assert_called_once()
        self.assertTrue(0 < mock_apply_async.call_args.kwargs["countdown"] < 2)
        self.assertEqual(
            redis_client.get(Polling._SINGLETON_REDIS_KEY),
            Polling._encode_redis_key(mock_apply_async.call_args.kwargs["args"][0]),
        )

    @patch("posthog.tasks.poll_query_performance.poll_query_performance")
    @patch("posthog.tasks.tasks.logger.error")
    @patch("posthog.tasks.tasks.poll_query_performance.delay")
    # Stub the inner query worker the task delegates to (a different module that happens to share
    # the name — not the task under test): the real worker makes extra time.time_ns() calls that
    # would exhaust the 2-value mock below and flake with StopIteration.
    @patch("posthog.tasks.poll_query_performance.poll_query_performance", MagicMock())
    @patch("time.time_ns", MagicMock(side_effect=[int(1e9), int(4e9)]))
    def test_poll_query_performance_runs_and_restarts_itself_with_no_delay_if_it_takes_too_long(
        self, mock_delay: MagicMock, mock_logger_error: MagicMock, mock_poll_query_performance_nontask: MagicMock
    ) -> None:
        redis_client = get_client()
        key = 1234
        encoded_key = Polling._encode_redis_key(key)
        redis_client.set(Polling._SINGLETON_REDIS_KEY, encoded_key)
        posthog.tasks.tasks.poll_query_performance(key)

        mock_logger_error.assert_not_called()
        new_key = int(1e9)
        mock_delay.assert_called_once_with(new_key)
        self.assertEqual(redis_client.get(Polling._SINGLETON_REDIS_KEY), new_key.to_bytes(8, "big"))

    @patch("posthog.tasks.tasks.logger.error")
    @patch("posthog.tasks.tasks.poll_query_performance.delay")
    @patch("time.time_ns", MagicMock(side_effect=[0, int(1e9), int(15e9)]))
    def test_start_poll_query_performance_does_nothing_for_14_seconds(
        self, mock_delay: MagicMock, mock_logger_error: MagicMock
    ) -> None:
        redis_client = get_client()
        key = int(1e9).to_bytes(8, "big")
        redis_client.set(Polling._SINGLETON_REDIS_KEY, key)
        for _ in range(3):
            posthog.tasks.tasks.start_poll_query_performance()
            mock_delay.assert_not_called()
            mock_logger_error.assert_not_called()

    @patch("posthog.tasks.tasks.logger.error")
    @patch("posthog.tasks.tasks.poll_query_performance.delay")
    @patch("time.time_ns", MagicMock(side_effect=[int(16e9)]))
    def test_start_poll_query_performance_starts_after_14(
        self, mock_delay: MagicMock, mock_logger_error: MagicMock
    ) -> None:
        redis_client = get_client()
        key = int(1e9)
        redis_client.set(Polling._SINGLETON_REDIS_KEY, Polling._encode_redis_key(key))
        posthog.tasks.tasks.start_poll_query_performance()
        mock_delay.assert_called_once_with(key)
        mock_logger_error.assert_called_once_with("Restarting poll query performance because of a long delay")

    @patch("posthog.tasks.tasks.logger.error")
    @patch("posthog.tasks.tasks.poll_query_performance.delay")
    @patch("time.time_ns", MagicMock(side_effect=[int(17e9)]))
    def test_start_poll_query_performance_errors_if_key_is_in_future_starts_anyway(
        self, mock_delay: MagicMock, mock_logger_error: MagicMock
    ) -> None:
        redis_client = get_client()
        key = 2**63  # in the future
        redis_client.set(Polling._SINGLETON_REDIS_KEY, Polling._encode_redis_key(key))
        posthog.tasks.tasks.start_poll_query_performance()
        mock_delay.assert_called_once_with(key)
        mock_logger_error.assert_called_once_with("Restarting poll query performance because key is in future")
