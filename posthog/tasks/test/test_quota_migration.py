import os
import sys
import tempfile
import subprocess

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.quota_migration import QUOTA_COMPARE_MISMATCHES
from posthog.redis import get_client
from posthog.tasks.quota_migration import compare_quota_redis, schedule_quota_redis_comparison
from posthog.tasks.scheduled import setup_periodic_tasks


class TestQuotaMigrationTasks(SimpleTestCase):
    @parameterized.expand([("disabled", None, 0), ("enabled", "redis://quota-task.test:6379/0", 1)])
    def test_schedule_requires_secondary_url(self, _name: str, url: str | None, expected: int) -> None:
        with self.settings(QUOTA_LIMITING_REDIS_URL=url), patch.object(compare_quota_redis, "apply_async") as enqueue:
            with patch("posthog.tasks.quota_migration.random.randint", return_value=123):
                schedule_quota_redis_comparison.run()
        self.assertEqual(enqueue.call_count, expected)
        if expected:
            enqueue.assert_called_once_with(countdown=123, expires=600)

    @parameterized.expand([("disabled", None, 0), ("enabled", "redis://quota-task.test:6379/0", 1)])
    def test_beat_entry_requires_secondary_url(self, _name: str, url: str | None, expected: int) -> None:
        sender = MagicMock()
        with self.settings(QUOTA_LIMITING_REDIS_URL=url):
            setup_periodic_tasks(sender)
        calls = [
            call for call in sender.add_periodic_task.call_args_list if call.kwargs.get("name") == "compare-quota-redis"
        ]
        self.assertEqual(len(calls), expected)
        if calls:
            self.assertEqual(calls[0].args[1].task, schedule_quota_redis_comparison.name)

    @parameterized.expand(
        [
            ("limits_events", "@posthog/quota-limits/events"),
            ("limits_recordings", "@posthog/quota-limits/recordings"),
            ("suspended_events", "@posthog/quota-limiting-suspended/events"),
            ("suspended_recordings", "@posthog/quota-limiting-suspended/recordings"),
        ]
    )
    @override_settings(QUOTA_LIMITING_REDIS_URL="redis://quota-task.test:6379/0")
    def test_comparison_reads_existing_quota_keys(self, _name: str, key: str) -> None:
        shared = get_client()
        secondary = get_client("redis://quota-task.test:6379/0")
        shared.flushdb()
        secondary.flushdb()
        self.addCleanup(shared.flushdb)
        self.addCleanup(secondary.flushdb)
        shared.zadd(key, {"missing": 1900000000})
        QUOTA_COMPARE_MISMATCHES.labels(key=key).set(0)
        with patch("posthog.quota_migration.sleep"):
            compare_quota_redis.run()
        self.assertEqual(QUOTA_COMPARE_MISMATCHES.labels(key=key)._value.get(), 1)

    @parameterized.expand([("disabled", ""), ("enabled", "redis://quota-task.test:6379/0")])
    def test_worker_metrics_survive_cleanup_fork_and_child_replacement(self, _name: str, url: str) -> None:
        script = """
import os
import time
import django
from unittest.mock import patch
django.setup()
from celery.signals import worker_process_init
from posthog.celery import on_celeryd_init
from posthog.quota_migration import QUOTA_COMPARE_FAILURES
from prometheus_client import CollectorRegistry, multiprocess
before = time.time()
import posthog.tasks.quota_migration as tasks
after = time.time()
for receiver in worker_process_init._live_receivers(None):
    if receiver.__module__ != tasks.__name__:
        worker_process_init.disconnect(receiver)
on_celeryd_init()
registry = CollectorRegistry()
multiprocess.MultiProcessCollector(registry)
starts = []
for generation in range(2):
    child = os.fork()
    if child == 0:
        with patch.object(tasks, 'time', return_value=after + 3600 * (generation + 1)):
            worker_process_init.send(sender=None)
        QUOTA_COMPARE_FAILURES.inc(0)
        os._exit(0)
    _, status = os.waitpid(child, 0)
    assert status == 0
    values = {sample.name: sample.value for metric in registry.collect() for sample in metric.samples}
    enabled = bool(os.environ.get('QUOTA_LIMITING_REDIS_URL'))
    assert values['billing_quota_migration_enabled'] == int(enabled), values
    started = values['billing_quota_migration_started_timestamp_seconds']
    if enabled:
        assert 0 < started <= after
    else:
        assert started == 0
    starts.append(started)
    multiprocess.mark_process_dead(child)
assert starts[0] == starts[1], starts
"""
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": directory, "QUOTA_LIMITING_REDIS_URL": url, "TEST": "1"}
            result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
