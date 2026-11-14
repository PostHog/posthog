import gc
import os
import logging
import threading

from unittest import TestCase
from unittest.mock import MagicMock, patch

from django.test import override_settings

import posthoganalytics
from celery.bootsteps import CLOSE, RUN, Blueprint
from celery.exceptions import WorkerShutdown
from celery.platforms import EX_FAILURE
from parameterized import parameterized
from prometheus_client import REGISTRY

import posthog.celery
from posthog.celery import (
    StopWorkerWhenEmbeddedSchedulerExits,
    _initialize_worker_metrics,
    drop_task_enqueued_logs_from_pool_processes,
    freeze_objects_before_pool_forks,
    on_worker_process_shutdown,
    receiver_setup_logging,
    write_heartbeat_when_worker_is_ready,
)
from posthog.celery_task_names import (
    VERIFY_FLAG_DEFINITIONS_CACHE_TASK_NAME,
    VERIFY_FLAGS_CACHE_TASK_NAME,
    VERIFY_TEAM_METADATA_CACHE_TASK_NAME,
)
from posthog.tasks.tasks import clickhouse_errors_count


class TestFreezeBeforePoolForks(TestCase):
    @parameterized.expand([(True,), (False,)])
    def test_freezes_the_objects_the_pool_will_inherit_only_when_enabled(self, enabled: bool) -> None:
        gc.unfreeze()
        self.addCleanup(gc.unfreeze)

        with override_settings(GC_FREEZE_BEFORE_POOL_FORK=enabled):
            freeze_objects_before_pool_forks()

        self.assertEqual(gc.get_freeze_count() > 0, enabled)


class TestWorkerShutdownFlushesAnalyticsMetrics(TestCase):
    def test_flushes_sdk_metrics_tail_window(self) -> None:
        client = MagicMock()
        with patch.object(posthoganalytics, "default_client", client):
            on_worker_process_shutdown()
        client.metrics.flush.assert_called_once()

    def test_hung_flush_does_not_stall_worker_recycling(self) -> None:
        release = threading.Event()
        flush_completed = threading.Event()

        def hung_flush() -> None:
            release.wait(timeout=10)
            flush_completed.set()

        client = MagicMock(**{"metrics.flush.side_effect": hung_flush})
        try:
            with (
                patch.object(posthog.celery, "_ANALYTICS_METRICS_FLUSH_TIMEOUT_SECONDS", 0.05),
                patch.object(posthoganalytics, "default_client", client),
            ):
                on_worker_process_shutdown()
            # The handler must abandon the hung flush, not wait it out.
            assert not flush_completed.is_set()
        finally:
            release.set()

    @parameterized.expand(
        [
            ("no_default_client", lambda: None),
            # The pinned SDK version has no `metrics` API — the hook must stay
            # inert (a bare `client.metrics.flush()` would raise on every
            # worker recycle until the dependency is bumped).
            (
                "real_client_on_pinned_sdk_version",
                lambda: posthoganalytics.Client("phc_test", sync_mode=True, disabled=True),
            ),
            ("flush_raises", lambda: MagicMock(**{"metrics.flush.side_effect": RuntimeError("network down")})),
        ]
    )
    def test_handler_never_breaks_worker_shutdown(self, _name: str, client_factory) -> None:
        with patch.object(posthoganalytics, "default_client", client_factory()):
            on_worker_process_shutdown()


class TestWorkerReadyHeartbeat(TestCase):
    @parameterized.expand([("hobby", True, 1), ("not_hobby", False, 0)])
    def test_writes_heartbeat_only_on_hobby(self, _name: str, hobby: bool, expected_calls: int) -> None:
        with (
            patch("posthog.cloud_utils.is_hobby", return_value=hobby),
            patch("posthog.tasks.tasks.redis_heartbeat") as heartbeat,
        ):
            write_heartbeat_when_worker_is_ready()
        assert heartbeat.call_count == expected_calls


class TestWorkerStopsWhenEmbeddedSchedulerExits(TestCase):
    def _registered_check(self, worker: MagicMock) -> MagicMock:
        # Through a real blueprint, because Celery calls register_with_event_loop only on the steps
        # that the blueprint keeps, and it calls it again after each broker reconnect.
        worker.steps = []
        blueprint = Blueprint(steps=[StopWorkerWhenEmbeddedSchedulerExits])
        blueprint.apply(worker)
        hub = MagicMock()
        blueprint.send_all(worker, "register_with_event_loop", args=(hub,))
        return hub.call_repeatedly

    def test_the_worker_app_has_the_step(self) -> None:
        assert StopWorkerWhenEmbeddedSchedulerExits in posthog.celery.app.steps["worker"]

    def test_worker_without_embedded_scheduler_runs_no_check(self) -> None:
        self._registered_check(MagicMock(beat=None)).assert_not_called()

    @parameterized.expand(
        [
            # A scheduler that waits for the RedBeat lock is alive, so its worker must keep running.
            ("scheduler_alive", True, RUN, False),
            ("scheduler_exited", False, RUN, True),
            # A worker that stops ends its own scheduler, which is not a failure to report.
            ("scheduler_ended_by_stopping_worker", False, CLOSE, False),
        ]
    )
    def test_stops_the_worker_only_when_its_scheduler_exited(
        self, _name: str, scheduler_alive: bool, worker_state: int, expect_shutdown: bool
    ) -> None:
        worker = MagicMock(**{"beat.is_alive.return_value": scheduler_alive, "blueprint.state": worker_state})
        _interval, check = self._registered_check(worker).call_args.args

        if not expect_shutdown:
            check()
            return
        # WorkerShutdown is the exception that Celery's own remote shutdown raises inside the event
        # loop. The loop logs and drops an ordinary Exception, and the worker would keep running.
        with self.assertRaises(WorkerShutdown) as shutdown:
            check()
        assert shutdown.exception.code == EX_FAILURE


class TestCeleryProcessLogging(TestCase):
    @parameterized.expand(
        [
            ("pool_process_drops_the_info_line", drop_task_enqueued_logs_from_pool_processes, {}, False),
            (
                "logging_setup_keeps_the_info_line_for_the_scheduler",
                receiver_setup_logging,
                {"loglevel": None, "logfile": None, "format": None, "colorize": False},
                True,
            ),
        ]
    )
    def test_task_enqueued_level(self, _name: str, process_hook, kwargs: dict, info_line_is_logged: bool) -> None:
        receivers_logger = logging.getLogger("django_structlog.celery.receivers")
        self.addCleanup(receivers_logger.setLevel, receivers_logger.level)
        receivers_logger.setLevel(logging.DEBUG)

        with patch("logging.config.dictConfig"):
            process_hook(**kwargs)

        assert receivers_logger.isEnabledFor(logging.INFO) is info_line_is_logged
        assert receivers_logger.isEnabledFor(logging.WARNING)


class TestAnalyticsMetricsConfig(TestCase):
    def test_apps_ready_configures_module_level_metrics(self) -> None:
        # Deleting the "unused" attr assignment in apps.py before the SDK bump
        # would make the bump silently ship service_name='unknown_service'.
        config = getattr(posthoganalytics, "metrics", None)
        assert isinstance(config, dict)
        assert config["service_name"]


class TestWorkerMetricsInitialization(TestCase):
    # "celery" excludes long_running, so this also proves the seed does not depend on
    # the queue set (and keeps the DB-touching cohort branch off).
    @patch.dict(os.environ, {"CELERY_WORKER_QUEUES": "celery"})
    def test_seeds_hypercache_verification_task_series(self) -> None:
        _initialize_worker_metrics()

        for task_name in (
            VERIFY_FLAGS_CACHE_TASK_NAME,
            VERIFY_TEAM_METADATA_CACHE_TASK_NAME,
            VERIFY_FLAG_DEFINITIONS_CACHE_TASK_NAME,
        ):
            for sample_name in (
                "posthog_celery_task_pre_run_total",
                "posthog_celery_task_success_total",
                "posthog_celery_task_failure_total",
            ):
                # Existence, not == 0: another test running one of these tasks in the
                # same process increments the counter, and the alert only needs the
                # series to exist.
                assert REGISTRY.get_sample_value(sample_name, {"task_name": task_name}) is not None, (
                    f"{sample_name} has no series for {task_name}"
                )


class TestCeleryMetrics(TestCase):
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.metrics.push_to_gateway")
    @patch("django.conf.settings.PROM_PUSHGATEWAY_ADDRESS", value="127.0.0.1")
    def test_clickhouse_errors_count(self, _, mock_push_to_gateway, mock_sync_execute):
        mock_sync_execute.return_value = [["ch1", "1", "NO_ZOOKEEPER", 123, 60]]
        clickhouse_errors_count()
        self.assertEqual(1, mock_push_to_gateway.call_count)
        registry = mock_push_to_gateway.call_args[1]["registry"]
        self.assertEqual(
            60,
            registry.get_sample_value(
                "posthog_celery_clickhouse_errors",
                labels={"name": "NO_ZOOKEEPER", "replica": "ch1", "shard": "1"},
            ),
        )
