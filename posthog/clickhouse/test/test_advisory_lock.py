"""Unit tests for advisory locking in tracking.py.

Tests acquire_apply_lock and release_apply_lock with mocked ClickHouse
client — no Django or ClickHouse connection required.
"""

from __future__ import annotations

from datetime import UTC, datetime

import unittest
from unittest.mock import MagicMock, patch

import posthog.clickhouse.test._stubs  # noqa: F401
from posthog.clickhouse.migration_tools.tracking import acquire_apply_lock, release_apply_lock


class TestAdvisoryLock(unittest.TestCase):
    """Tests for the advisory lock mechanism."""

    @patch("posthog.clickhouse.migration_tools.tracking.time.sleep")
    def test_advisory_lock_prevents_concurrent_apply(self, mock_sleep: MagicMock) -> None:
        """An active lock from another host prevents acquisition."""
        client = MagicMock()
        now = datetime.now(tz=UTC)
        # Flow: ensure table, check for existing lock (found -> reject)
        client.execute.side_effect = [
            None,  # CREATE TABLE ON CLUSTER (ensure tracking table)
            [("other-pod", now)],  # Check SELECT -- another host holds the lock
        ]

        acquired, reason = acquire_apply_lock(client, "default", "my-pod")

        self.assertFalse(acquired)
        self.assertIn("other-pod", reason)
        self.assertIn("--force", reason)

    @patch("posthog.clickhouse.migration_tools.tracking.time.sleep")
    def test_advisory_lock_expired_allows_apply(self, mock_sleep: MagicMock) -> None:
        """No active lock (expired or absent) allows acquisition."""
        client = MagicMock()
        now = datetime.now(tz=UTC)
        client.execute.side_effect = [
            None,  # CREATE TABLE ON CLUSTER (ensure tracking table)
            [],  # Check SELECT -- no active lock
            None,  # INSERT lock row (via _record_step)
            None,  # SYSTEM SYNC REPLICA (replication barrier)
            [("my-pod", now)],  # Post-replication verify -- only our lock
        ]

        acquired, reason = acquire_apply_lock(client, "default", "my-pod")

        self.assertTrue(acquired)
        self.assertEqual(reason, "")
        # Five calls: CREATE ON CLUSTER + check SELECT + INSERT + SYNC REPLICA + verify SELECT
        self.assertEqual(client.execute.call_count, 5)
        # SYNC REPLICA succeeded, so no sleep fallback
        mock_sleep.assert_not_called()
        sync_sql = client.execute.call_args_list[3].args[0]
        self.assertIn("SYSTEM SYNC REPLICA", sync_sql)
        self.assertIn("STRICT", sync_sql)
        verify_sql = client.execute.call_args_list[4].args[0]
        self.assertIn("ORDER BY applied_at ASC, host ASC", verify_sql)

    @patch("posthog.clickhouse.migration_tools.tracking.time.sleep")
    def test_advisory_lock_same_host_allows_reacquire(self, mock_sleep: MagicMock) -> None:
        """A lock from the same host allows re-acquisition (idempotent)."""
        client = MagicMock()
        now = datetime.now(tz=UTC)
        client.execute.side_effect = [
            None,  # CREATE TABLE ON CLUSTER
            [],  # Check SELECT -- no lock from OTHER hosts
            None,  # INSERT lock row
            None,  # SYSTEM SYNC REPLICA
            [("my-pod", now)],  # Verify -- our own host holds the lock
        ]

        acquired, reason = acquire_apply_lock(client, "default", "my-pod")

        self.assertTrue(acquired)
        self.assertEqual(reason, "")

    @patch("posthog.clickhouse.migration_tools.tracking.time.sleep")
    def test_advisory_lock_force_skips_precheck_but_still_verifies(self, mock_sleep: MagicMock) -> None:
        """force=True skips the pre-check SELECT but still runs INSERT + SYNC + verify."""
        client = MagicMock()
        now = datetime.now(tz=UTC)
        client.execute.side_effect = [
            None,  # CREATE TABLE ON CLUSTER
            None,  # INSERT lock row (no pre-check SELECT)
            None,  # SYSTEM SYNC REPLICA
            [("my-pod", now)],  # Verify -- only our lock
        ]

        acquired, reason = acquire_apply_lock(client, "default", "my-pod", force=True)

        self.assertTrue(acquired)
        self.assertEqual(reason, "")
        # Four calls: CREATE + INSERT + SYNC + verify (no pre-check SELECT)
        self.assertEqual(client.execute.call_count, 4)

    @patch("posthog.clickhouse.migration_tools.tracking.time.sleep")
    def test_advisory_lock_force_logs_warning_when_other_host_wins(self, mock_sleep: MagicMock) -> None:
        """force=True returns acquired when verify shows another host, logging a warning."""
        client = MagicMock()
        now = datetime.now(tz=UTC)
        client.execute.side_effect = [
            None,  # CREATE TABLE ON CLUSTER
            None,  # INSERT lock row
            None,  # SYSTEM SYNC REPLICA
            [("other-pod", now), ("my-pod", now)],  # Verify -- other-pod won the tie-break
        ]

        with self.assertLogs("posthog.clickhouse.migration_tools.tracking", level="WARNING") as cm:
            acquired, reason = acquire_apply_lock(client, "default", "my-pod", force=True)

        self.assertTrue(acquired)
        self.assertEqual(reason, "")
        self.assertTrue(any("other-pod" in line for line in cm.output))

    @patch("posthog.clickhouse.migration_tools.tracking.time.sleep")
    def test_advisory_lock_race_detected(self, mock_sleep: MagicMock) -> None:
        """When two hosts both insert before replication, the loser backs off."""
        client = MagicMock()
        now = datetime.now(tz=UTC)
        client.execute.side_effect = [
            None,  # CREATE TABLE ON CLUSTER
            [],  # Check SELECT -- no lock (race window)
            None,  # INSERT lock row
            None,  # SYSTEM SYNC REPLICA
            [("other-pod", now), ("my-pod", now)],  # Verify -- two locks! other-pod won
            None,  # release_apply_lock INSERT (direction=down)
        ]

        acquired, reason = acquire_apply_lock(client, "default", "my-pod")

        self.assertFalse(acquired)
        self.assertIn("Race detected", reason)
        self.assertIn("other-pod", reason)

    def test_release_apply_lock_inserts_down_row(self) -> None:
        """Release inserts a direction='down', success=True row."""
        client = MagicMock()
        client.execute.return_value = None

        release_apply_lock(client, "default", "my-pod")

        # Should have inserted a row (via _record_step which calls client.execute)
        client.execute.assert_called_once()
        # Verify the INSERT contains direction='down'
        call_args = client.execute.call_args
        params = call_args[0][1][0]  # positional: (sql, params_list)
        # direction is at index 5 in the tuple
        self.assertEqual(params[5], "down")
        # success is at index 8
        self.assertTrue(params[8])

    def test_tracking_table_ddl_uses_replicated_engine(self) -> None:
        """The tracking table DDL must use ReplicatedMergeTree and ON CLUSTER."""
        from posthog.clickhouse.migration_tools.tracking import TRACKING_TABLE_DDL

        self.assertIn("ReplicatedMergeTree", TRACKING_TABLE_DDL)
        self.assertIn("ON CLUSTER", TRACKING_TABLE_DDL)
        self.assertIn("{cluster}", TRACKING_TABLE_DDL)
        self.assertIn("{{shard}}", TRACKING_TABLE_DDL)
        self.assertIn("{{replica}}", TRACKING_TABLE_DDL)


class TestSyncReplicaFallback(unittest.TestCase):
    """SYNC REPLICA exception routing in acquire_apply_lock."""

    @patch("posthog.clickhouse.migration_tools.tracking.time.sleep")
    def test_not_replicated_error_swallowed(self, mock_sleep: MagicMock) -> None:
        """'is not replicated' exception is caught and replaced by a brief sleep."""
        client = MagicMock()
        now = datetime.now(tz=UTC)
        client.execute.side_effect = [
            None,  # CREATE TABLE
            [],  # Pre-check SELECT — no existing lock
            None,  # INSERT lock row
            Exception("Table default.clickhouse_schema_migrations is not replicated"),
            [("my-pod", now)],  # Verify
        ]

        acquired, _ = acquire_apply_lock(client, "default", "my-pod")

        self.assertTrue(acquired)
        mock_sleep.assert_called_once_with(1)

    @patch("posthog.clickhouse.migration_tools.tracking.time.sleep")
    def test_not_implemented_error_swallowed(self, mock_sleep: MagicMock) -> None:
        """'NOT_IMPLEMENTED' exception (alt ClickHouse error code) is also swallowed."""
        client = MagicMock()
        now = datetime.now(tz=UTC)
        client.execute.side_effect = [
            None,
            [],
            None,
            Exception("Code: 48. DB::Exception: NOT_IMPLEMENTED"),
            [("my-pod", now)],
        ]

        acquired, _ = acquire_apply_lock(client, "default", "my-pod")

        self.assertTrue(acquired)
        mock_sleep.assert_called_once_with(1)

    @patch("posthog.clickhouse.migration_tools.tracking.time.sleep")
    def test_zookeeper_error_reraises(self, mock_sleep: MagicMock) -> None:
        """Replication failures that are NOT 'is not replicated' re-raise so caller aborts."""
        client = MagicMock()
        client.execute.side_effect = [
            None,
            [],
            None,
            Exception("ZooKeeper session expired"),
        ]

        with self.assertRaises(Exception, msg="ZooKeeper session expired"):
            acquire_apply_lock(client, "default", "my-pod")

        mock_sleep.assert_not_called()


class TestSchemaVersion(unittest.TestCase):
    """Tests for record_schema_version and get_latest_schema_version."""

    def test_record_schema_version_inserts_correct_sentinel(self) -> None:
        """record_schema_version inserts a row with VERSION_STEP_INDEX and commit_hash."""
        from posthog.clickhouse.migration_tools.tracking import VERSION_STEP_INDEX, record_schema_version

        client = MagicMock()
        client.execute.return_value = None

        record_schema_version(client, "default", "abc123", "my-pod")

        client.execute.assert_called_once()
        call_args = client.execute.call_args
        params = call_args[0][1][0]  # (sql, params_list)[0]
        # migration_name at index 1
        self.assertEqual(params[1], "abc123")
        # step_index at index 2
        self.assertEqual(params[2], VERSION_STEP_INDEX)
        self.assertEqual(VERSION_STEP_INDEX, -2)
        # direction at index 5
        self.assertEqual(params[5], "up")
        # checksum at index 6
        self.assertEqual(params[6], "version")

    def test_get_latest_schema_version_returns_tuple(self) -> None:
        """get_latest_schema_version returns (commit_hash, host, applied_at_str) when a row exists."""
        from posthog.clickhouse.migration_tools.tracking import get_latest_schema_version

        client = MagicMock()
        now = datetime.now(tz=UTC)
        client.execute.return_value = [("abc123", "my-pod", now)]

        result = get_latest_schema_version(client, "default")

        self.assertIsNotNone(result)
        assert result is not None
        commit_hash, host, applied_at_str = result
        self.assertEqual(commit_hash, "abc123")
        self.assertEqual(host, "my-pod")
        self.assertEqual(applied_at_str, str(now))

    def test_get_latest_schema_version_returns_none_when_empty(self) -> None:
        """get_latest_schema_version returns None when the table has no version rows."""
        from posthog.clickhouse.migration_tools.tracking import get_latest_schema_version

        client = MagicMock()
        client.execute.return_value = []

        result = get_latest_schema_version(client, "default")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
