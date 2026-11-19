import os
import sys
import tempfile
import subprocess
from datetime import UTC, datetime

import time_machine
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY
from redis.client import Pipeline
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    RedisClusterException,
    TimeoutError as RedisTimeoutError,
)
from structlog.testing import capture_logs

from posthog import quota_redis
from posthog.quota_migration import (
    QUOTA_COMPARE_LAST_SUCCESS,
    QUOTA_COMPARE_MISMATCHES,
    _retry_after,
    compare_quota_stores,
    snapshot_quota_stores,
)
from posthog.quota_redis import clear_quota_redis_clients
from posthog.redis import get_client

from ee.billing.quota_limiting import (
    QuotaLimitingCaches,
    QuotaResource,
    add_limited_team_tokens,
    reconcile_limited_team_tokens,
    remove_limited_team_tokens,
)


@override_settings(
    QUOTA_LIMITING_REDIS_URL="redis://quota-secondary.test:6379/0",
    QUOTA_LIMITING_REDIS_CLUSTER_ENABLED=False,
)
@time_machine.travel("2026-11-12T12:00:00Z", tick=False)
class TestQuotaMigration(SimpleTestCase):
    key = "@posthog/quota-limits/events"
    resource = QuotaResource.EVENTS
    cache = QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY

    def setUp(self) -> None:
        _retry_after.clear()
        self.addCleanup(_retry_after.clear)
        clear_quota_redis_clients()
        self.addCleanup(clear_quota_redis_clients)
        self.shared = get_client()
        self.secondary = get_client("redis://quota-secondary.test:6379/0")
        self.shared.flushdb()
        self.secondary.flushdb()

    @parameterized.expand([("add",), ("remove",)])
    def test_mutations_reach_both_stores(self, operation: str) -> None:
        for client in (self.shared, self.secondary):
            client.zadd(self.key, {"existing": 1900000000})

        if operation == "add":
            add_limited_team_tokens(self.resource, {"new": 1900000100}, self.cache)
            expected = [(b"existing", 1900000000.0), (b"new", 1900000100.0)]
        else:
            remove_limited_team_tokens(self.resource, ["existing"], self.cache)
            expected = []

        assert self.shared.zrange(self.key, 0, -1, withscores=True) == expected
        assert self.secondary.zrange(self.key, 0, -1, withscores=True) == expected

    def test_bulk_writes_send_no_script_commands(self) -> None:
        for client in (self.shared, self.secondary):
            client.zadd(self.key, {"existing": 1900000000})
        snapshots = snapshot_quota_stores({self.key: ["existing"]})
        with (
            patch.object(quota_redis, "monotonic", return_value=100, create=True),
            patch.object(self.shared, "execute_command", wraps=self.shared.execute_command) as shared_commands,
            patch.object(
                Pipeline, "execute_command", autospec=True, side_effect=Pipeline.execute_command
            ) as pipeline_commands,
            patch.object(self.secondary, "execute_command", wraps=self.secondary.execute_command) as secondary_commands,
        ):
            reconcile_limited_team_tokens(
                self.resource, ["existing"], {"new": 1900000100}, self.cache, store_snapshots=snapshots
            )
        commands = [call.args[0] for call in shared_commands.call_args_list + secondary_commands.call_args_list]
        commands.extend(call.args[1] for call in pipeline_commands.call_args_list)
        assert not any(str(command).upper().split()[0] in {"EVAL", "EVALSHA", "SCRIPT"} for command in commands)
        for client in (self.shared, self.secondary):
            assert client.zrange(self.key, 0, -1, withscores=True) == [(b"new", 1900000100.0)]

    @parameterized.expand(
        [
            ("stale", {"stale": 1900000000}, ["stale"], {}, {}),
            ("additions", {}, [], {"new": 1900000100}, {b"new": 1900000100.0}),
            (
                "both",
                {"stale": 1900000000, "kept": 1900000000},
                ["stale", "kept"],
                {"kept": 1900000100, "new": 1900000200},
                {b"kept": 1900000100.0, b"new": 1900000200.0},
            ),
            ("empty", {}, [], {}, {}),
            ("expires_now", {"expired": 1794484800}, [], {}, {}),
        ]
    )
    def test_reconcile_matches_shared_state(
        self,
        _name: str,
        initial: dict[str, int],
        selected: list[str],
        tokens: dict[str, int],
        expected: dict[bytes, float],
    ) -> None:
        for client in (self.shared, self.secondary):
            if initial:
                client.zadd(self.key, initial)  # type: ignore[arg-type]
        snapshots = snapshot_quota_stores({self.key: selected})
        with (
            patch.object(quota_redis, "QUOTA_WRITE_BATCH_SIZE", 2, create=True),
            patch.object(quota_redis, "monotonic", return_value=100, create=True),
            patch.object(self.secondary, "execute_command", wraps=self.secondary.execute_command) as commands,
        ):
            reconcile_limited_team_tokens(self.resource, selected, tokens, self.cache, store_snapshots=snapshots)
        assert dict(self.shared.zrange(self.key, 0, -1, withscores=True)) == expected
        assert dict(self.secondary.zrange(self.key, 0, -1, withscores=True)) == expected
        assert commands.call_args_list[0].args == ("ZREMRANGEBYSCORE", self.key, "-inf", 1794484800.0)

    @parameterized.expand(
        [(f"{command}_{batch}", command, batch) for command in ["ZREM", "ZADD"] for batch in [1, 2, 3]]
    )
    def test_failed_batch_preserves_shared_write_and_recovers(
        self, _name: str, command: str, failed_batch: int
    ) -> None:
        stale = {f"stale-{index}": 1900000000 for index in range(5)}
        tokens = {f"new-{index}": 1900000100 for index in range(5)}
        for client in (self.shared, self.secondary):
            client.zadd(self.key, stale)  # type: ignore[arg-type]
        snapshots = snapshot_quota_stores({self.key: list(stale)})
        labels = {"operation": "reconcile", "result": "failure"}
        before = REGISTRY.get_sample_value("billing_quota_secondary_operations_total", labels) or 0
        execute = self.secondary.execute_command
        seen_batches = 0

        def fail_batch(*arguments: object, **options: object) -> object:
            nonlocal seen_batches
            if arguments[0] == command:
                seen_batches += 1
                if seen_batches == failed_batch:
                    raise RedisTimeoutError("batch unavailable")
            return execute(*arguments, **options)

        with (
            patch.object(quota_redis, "QUOTA_WRITE_BATCH_SIZE", 2, create=True),
            patch.object(quota_redis, "monotonic", return_value=100, create=True),
            patch("posthog.quota_migration.monotonic", return_value=100),
            patch.object(self.secondary, "execute_command", side_effect=fail_batch) as commands,
        ):
            reconcile_limited_team_tokens(self.resource, list(stale), tokens, self.cache, store_snapshots=snapshots)
        expected_prefix = ["ZREMRANGEBYSCORE"]
        if command == "ZADD":
            expected_prefix += ["ZREM"] * 3
        assert [call.args[0] for call in commands.call_args_list] == expected_prefix + [command] * failed_batch
        assert dict(self.shared.zrange(self.key, 0, -1, withscores=True)) == {
            token.encode(): float(score) for token, score in tokens.items()
        }
        assert REGISTRY.get_sample_value("billing_quota_secondary_operations_total", labels) == before + 1
        assert _retry_after["redis://quota-secondary.test:6379/0"] == 130
        with (
            patch.object(quota_redis, "QUOTA_WRITE_BATCH_SIZE", 2, create=True),
            patch.object(quota_redis, "monotonic", return_value=131, create=True),
            patch("posthog.quota_migration.monotonic", return_value=131),
        ):
            snapshots = snapshot_quota_stores({self.key: list(tokens)})
            reconcile_limited_team_tokens(self.resource, list(tokens), tokens, self.cache, store_snapshots=snapshots)
        assert self.secondary.zrange(self.key, 0, -1, withscores=True) == self.shared.zrange(
            self.key, 0, -1, withscores=True
        )
        assert REGISTRY.get_sample_value("billing_quota_secondary_operations_total", labels) == before + 1

    @parameterized.expand([(completed,) for completed in [0, 1, 3, 4, 6]])
    def test_expired_write_budget_preserves_shared_write(self, completed: int) -> None:
        stale = {f"stale-{index}": 1900000000 for index in range(5)}
        tokens = {f"new-{index}": 1900000100 for index in range(5)}
        for client in (self.shared, self.secondary):
            client.zadd(self.key, stale)  # type: ignore[arg-type]
        snapshots = snapshot_quota_stores({self.key: list(stale)})
        labels = {"operation": "reconcile", "result": "failure"}
        before = REGISTRY.get_sample_value("billing_quota_secondary_operations_total", labels) or 0
        execute = self.secondary.execute_command
        elapsed = 0

        def advance_clock(*arguments: object, **options: object) -> object:
            nonlocal elapsed
            result = execute(*arguments, **options)
            elapsed += 10
            return result

        with (
            patch.object(quota_redis, "QUOTA_WRITE_BATCH_SIZE", 2, create=True),
            patch.object(quota_redis, "QUOTA_WRITE_BUDGET_SECONDS", completed * 10, create=True),
            patch.object(quota_redis, "monotonic", side_effect=lambda: 100 + elapsed, create=True),
            patch("posthog.quota_migration.monotonic", return_value=100),
            patch.object(self.secondary, "execute_command", side_effect=advance_clock) as commands,
        ):
            reconcile_limited_team_tokens(self.resource, list(stale), tokens, self.cache, store_snapshots=snapshots)
        assert commands.call_count == completed
        assert dict(self.shared.zrange(self.key, 0, -1, withscores=True)) == {
            token.encode(): float(score) for token, score in tokens.items()
        }
        assert REGISTRY.get_sample_value("billing_quota_secondary_operations_total", labels) == before + 1
        assert _retry_after["redis://quota-secondary.test:6379/0"] == 130

    @parameterized.expand([("reconcile",), ("snapshot",), ("compare",)])
    def test_bulk_operations_use_the_maintenance_connection(self, operation: str) -> None:
        snapshots = snapshot_quota_stores({self.key: []})
        with patch(
            "posthog.quota_migration.get_secondary_quota_redis_client", return_value=self.secondary
        ) as get_secondary:
            if operation == "reconcile":
                reconcile_limited_team_tokens(self.resource, [], {}, self.cache, store_snapshots=snapshots)
            elif operation == "snapshot":
                snapshot_quota_stores({self.key: []})
            else:
                compare_quota_stores([self.key])
        get_secondary.assert_called_once_with(maintenance=True)

    def test_secondary_failure_does_not_fail_shared_write(self) -> None:
        with patch.object(self.secondary, "zadd", side_effect=RedisTimeoutError("secondary unavailable")):
            add_limited_team_tokens(self.resource, {"new": 1900000100}, self.cache)

        assert self.shared.zscore(self.key, "new") == 1900000100
        assert self.secondary.zscore(self.key, "new") is None

    def test_secondary_client_failure_does_not_fail_shared_write(self) -> None:
        labels = {"operation": "add", "result": "failure"}
        before = REGISTRY.get_sample_value("billing_quota_secondary_operations_total", labels) or 0
        with patch(
            "posthog.quota_migration.get_secondary_quota_redis_client",
            side_effect=RedisConnectionError("secondary unavailable"),
        ):
            add_limited_team_tokens(self.resource, {"new": 1900000100}, self.cache)

        assert self.shared.zscore(self.key, "new") == 1900000100
        assert self.secondary.zscore(self.key, "new") is None
        assert REGISTRY.get_sample_value("billing_quota_secondary_operations_total", labels) == before + 1

    def test_shared_failure_stops_the_write(self) -> None:
        with (
            patch.object(self.shared, "zadd", side_effect=RedisTimeoutError("shared unavailable")),
            self.assertRaises(RedisTimeoutError),
        ):
            add_limited_team_tokens(self.resource, {"new": 1900000100}, self.cache)

        assert self.secondary.zscore(self.key, "new") is None

    def test_outage_cooldown_and_recovery(self) -> None:
        def count(result: str) -> float:
            labels = {"operation": "add", "result": result}
            return REGISTRY.get_sample_value("billing_quota_secondary_operations_total", labels) or 0

        before = {result: count(result) for result in ("failure", "cooldown", "success")}
        sensitive_message = "redis://user:secret@quota-secondary.test/0 member=private-token"
        with (
            capture_logs() as logs,
            patch("posthog.quota_migration.monotonic", return_value=100),
            patch.object(self.secondary, "zadd", side_effect=RedisTimeoutError(sensitive_message)) as write,
        ):
            add_limited_team_tokens(self.resource, {"first": 1900000100}, self.cache)
            add_limited_team_tokens(self.resource, {"second": 1900000100}, self.cache)
            assert write.call_count == 1
            assert count("failure") == before["failure"] + 1
        assert logs == [
            {
                "event": "quota_secondary_operation_failed",
                "operation": "add",
                "resource": self.key,
                "error_type": "TimeoutError",
                "log_level": "warning",
            }
        ]
        assert count("cooldown") == before["cooldown"] + 1
        with patch("posthog.quota_migration.monotonic", return_value=131):
            add_limited_team_tokens(self.resource, {"recovered": 1900000100}, self.cache)
        assert count("success") == before["success"] + 1
        assert self.shared.zcard(self.key) == 3
        assert self.secondary.zrange(self.key, 0, -1) == [b"recovered"]

    def test_reconciliation_uses_each_stores_snapshot(self) -> None:
        self.shared.zadd(self.key, {"shared-stale": 1900000000, "protected": 1900000000})
        self.secondary.zadd(self.key, {"secondary-stale": 1900000000, "protected": 1900000000})
        selected = ["shared-stale", "protected"]
        snapshots = snapshot_quota_stores({self.key: selected}).without_tokens({"protected"})
        # Neither store may remove an entry added after its own snapshot.
        self.shared.zadd(self.key, {"shared-concurrent": 1900000000})
        self.secondary.zadd(self.key, {"secondary-concurrent": 1900000000})
        reconcile_limited_team_tokens(
            self.resource, selected, {"limited": 1900000100}, self.cache, store_snapshots=snapshots
        )
        assert set(self.shared.zrange(self.key, 0, -1)) == {b"protected", b"shared-concurrent", b"limited"}
        assert set(self.secondary.zrange(self.key, 0, -1)) == {b"protected", b"secondary-concurrent", b"limited"}

    def test_failed_secondary_snapshot_skips_reconciliation_even_after_recovery(self) -> None:
        self.shared.zadd(self.key, {"old": 1900000000})
        self.secondary.zadd(self.key, {"unknown": 1900000000})
        with patch.object(self.secondary, "zrangebyscore", side_effect=RedisTimeoutError("unavailable")):
            snapshots = snapshot_quota_stores({self.key: ["old"]})
        _retry_after.clear()
        reconcile_limited_team_tokens(self.resource, ["old"], {}, self.cache, store_snapshots=snapshots)
        assert self.shared.zcard(self.key) == 0
        assert self.secondary.zrange(self.key, 0, -1) == [b"unknown"]

    @override_settings(QUOTA_LIMITING_REDIS_URL=None)
    def test_unconfigured_secondary_preserves_shared_writes(self) -> None:
        add_limited_team_tokens(self.resource, {"new": 1900000100}, self.cache)
        assert self.shared.zscore(self.key, "new") == 1900000100
        assert self.secondary.zcard(self.key) == 0

    def test_comparison_rechecks_members_and_scores(self) -> None:
        self.shared.zadd(self.key, {"same": 10, "missing": 20, "score": 30, "in-flight": 40})
        self.secondary.zadd(self.key, {"same": 10, "extra": 20, "score": 31})

        def finish_write(_delay: float) -> None:
            self.secondary.zadd(self.key, {"in-flight": 40})

        with patch("posthog.quota_migration.sleep", side_effect=finish_write) as delay:
            assert compare_quota_stores([self.key])
        assert delay.call_count == 1
        assert QUOTA_COMPARE_MISMATCHES.labels(key=self.key)._value.get() == 3

    def test_changing_difference_does_not_count_as_persistent(self) -> None:
        self.shared.zadd(self.key, {"updating": 10})

        def update_again(_delay: float) -> None:
            self.shared.zadd(self.key, {"updating": 20})

        with patch("posthog.quota_migration.sleep", side_effect=update_again):
            assert compare_quota_stores([self.key])
        assert QUOTA_COMPARE_MISMATCHES.labels(key=self.key)._value.get() == 0

    def test_comparison_failure_keeps_previous_results(self) -> None:
        QUOTA_COMPARE_MISMATCHES.labels(key=self.key).set(7)
        QUOTA_COMPARE_LAST_SUCCESS.set(123)
        self.shared.zadd(self.key, {"missing": 10})
        with (
            capture_logs() as logs,
            patch("posthog.quota_migration.sleep"),
            patch.object(self.secondary, "zrange", side_effect=[[], RedisTimeoutError("member=private-token")]),
        ):
            assert not compare_quota_stores([self.key])
        assert logs == [{"event": "quota_comparison_failed", "error_type": "TimeoutError", "log_level": "warning"}]
        assert QUOTA_COMPARE_MISMATCHES.labels(key=self.key)._value.get() == 7
        assert QUOTA_COMPARE_LAST_SUCCESS._value.get() == 123

    @override_settings(REDIS_READER_URL="redis://shared-reader.test:6379/0")
    def test_comparison_reads_shared_replica_and_secondary_primary(self) -> None:
        reader = get_client("redis://shared-reader.test:6379/0")
        reader.flushdb()
        self.shared.zadd(self.key, {"primary-only": 10})
        with patch("posthog.quota_migration.sleep") as delay:
            assert compare_quota_stores([self.key])
        delay.assert_not_called()
        assert QUOTA_COMPARE_MISMATCHES.labels(key=self.key)._value.get() == 0

    def test_comparison_evidence_survives_celery_worker_recycling(self) -> None:
        worker = """
import os, sys
from posthog.quota_migration import QUOTA_COMPARE_MISMATCHES, QUOTA_COMPARE_LAST_SUCCESS
QUOTA_COMPARE_MISMATCHES.labels(key="@posthog/quota-limits/events").set(float(sys.argv[1]))
QUOTA_COMPARE_LAST_SUCCESS.set(float(sys.argv[2]))
print(os.getpid())
"""
        collector = """
import sys
from prometheus_client import CollectorRegistry, multiprocess
registry = CollectorRegistry()
multiprocess.MultiProcessCollector(registry)
def values():
    return {s.name: s.value for m in registry.collect() for s in m.samples}
before = values()
assert before["billing_quota_compare_mismatches"] == 7
assert before["billing_quota_compare_last_success_timestamp_seconds"] == 200
multiprocess.mark_process_dead(int(sys.argv[1]))
after = values()
assert after["billing_quota_compare_mismatches"] == 7
assert after["billing_quota_compare_last_success_timestamp_seconds"] == 200
"""
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": directory}
            subprocess.run([sys.executable, "-c", worker, "0", "100"], env=env, check=True, capture_output=True)
            newest = subprocess.run(
                [sys.executable, "-c", worker, "7", "200"], env=env, check=True, capture_output=True, text=True
            )
            result = subprocess.run(
                [sys.executable, "-c", collector, newest.stdout.strip()], env=env, capture_output=True, text=True
            )
            assert result.returncode == 0, result.stderr


@override_settings(
    REDIS_URL="redis://quota-cluster-commands:6379/0",
)
@time_machine.travel("2026-11-12T12:00:00Z", tick=False)
class TestQuotaWriteCommands(SimpleTestCase):
    def setUp(self) -> None:
        quota_redis.clear_quota_redis_clients()
        self.addCleanup(quota_redis.clear_quota_redis_clients)
        self.redis = get_client()
        self.redis.flushdb()
        self.addCleanup(self.redis.flushdb)
        self.key = f"{QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY.value}events"
        original_pipeline = self.redis.pipeline

        def cluster_pipeline(transaction: bool = True, shard_hint: str | None = None) -> Pipeline:
            if transaction:
                raise RedisClusterException("transactional pipelines are unsupported")
            return original_pipeline(transaction=False, shard_hint=shard_hint)

        pipeline_guard = patch.object(self.redis, "pipeline", side_effect=cluster_pipeline)
        pipeline_guard.start()
        self.addCleanup(pipeline_guard.stop)

    @parameterized.expand([(size,) for size in [0, 1, 2, 3, 7]])
    def test_bulk_writes_use_bounded_commands(self, size: int) -> None:
        stale = {f"stale-{index}": 1794571200 for index in range(size)}
        self.redis.zadd(self.key, {"expired": 1, **stale})  # type: ignore[dict-item]
        tokens = {f"team-{index}": 1794571300 + index for index in range(size)}
        with (
            patch.object(quota_redis, "QUOTA_WRITE_BATCH_SIZE", 2, create=True),
            patch.object(quota_redis, "monotonic", return_value=100, create=True),
            patch.object(self.redis, "pipeline", side_effect=AssertionError("Unexpected pipeline")),
            patch.object(self.redis, "execute_command", wraps=self.redis.execute_command) as commands,
        ):
            quota_redis.reconcile_quota_set(self.redis, self.key, iter(stale), tokens, 1794484800)
        batches = (size + 1) // 2
        expected_commands = ["ZREMRANGEBYSCORE"] + ["ZREM"] * batches
        assert [call.args[0] for call in commands.call_args_list] == expected_commands + ["ZADD"] * batches
        assert all(len(call.args) <= 6 for call in commands.call_args_list)
        actual = {token.decode(): score for token, score in self.redis.zrange(self.key, 0, -1, withscores=True)}
        assert actual == tokens

    def test_reconciliation_preserves_additions_missing_from_the_snapshot(self) -> None:
        self.redis.zadd(self.key, {"kept": 1794571200, "stale": 1794571200, "concurrent": 1794571200, "expired": 1})
        additions = {f"new-{i}": 1794571300 + i for i in range(5000)}
        stale = {f"stale-{i}": 1794571200 for i in range(5000)}
        self.redis.zadd(self.key, dict(stale.items()))

        quota_redis.reconcile_quota_set(
            self.redis,
            self.key,
            ["kept", "stale", "expired", *stale],
            {"kept": 1794571300, **additions},
            datetime(2026, 11, 12, 12, tzinfo=UTC).timestamp(),
        )

        actual = {token.decode(): score for token, score in self.redis.zrange(self.key, 0, -1, withscores=True)}
        self.assertEqual(actual, {"kept": 1794571300, "concurrent": 1794571200, **additions})
