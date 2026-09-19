import os
import threading

from unittest import TestCase
from unittest.mock import MagicMock, patch

import posthoganalytics
from celery.worker.control import Panel
from parameterized import parameterized
from prometheus_client import REGISTRY

import posthog.celery
from posthog.celery import _initialize_worker_metrics, on_worker_process_shutdown
from posthog.celery_control import EVENT_DISPATCHER_COMMANDS, EVENTS_DISABLED_REPLY
from posthog.celery_task_names import (
    VERIFY_FLAG_DEFINITIONS_CACHE_TASK_NAME,
    VERIFY_FLAGS_CACHE_TASK_NAME,
    VERIFY_TEAM_METADATA_CACHE_TASK_NAME,
)
from posthog.tasks.tasks import clickhouse_errors_count


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


class TestEventDispatcherControlCommands(TestCase):
    @parameterized.expand([(name,) for name in EVENT_DISPATCHER_COMMANDS])
    def test_command_replies_when_the_worker_has_no_event_dispatcher(self, command: str) -> None:
        # A worker run without task events, gossip and heartbeat keeps event_dispatcher at
        # None, and Celery's own handlers dereference it on every broadcast.
        state = MagicMock(**{"consumer.event_dispatcher": None})

        assert Panel.data[command](state) == {"ok": EVENTS_DISABLED_REPLY}

    def test_enable_events_still_adds_the_task_group(self) -> None:
        dispatcher = MagicMock(groups={"worker"})
        state = MagicMock(**{"consumer.event_dispatcher": dispatcher})

        assert Panel.data["enable_events"](state) == {"ok": "task events enabled"}
        assert "task" in dispatcher.groups
