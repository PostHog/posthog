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
            [("my-pod", now)],  # Post-replication verify -- only our lock
        ]

        acquired, reason = acquire_apply_lock(client, "default", "my-pod")

        self.assertTrue(acquired)
        self.assertEqual(reason, "")
        # Four calls: CREATE ON CLUSTER + check SELECT + INSERT + verify SELECT
        self.assertEqual(client.execute.call_count, 4)
        mock_sleep.assert_called_once_with(5)
        verify_sql = client.execute.call_args_list[3].args[0]
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
            [("my-pod", now)],  # Verify -- our own host holds the lock
        ]

        acquired, reason = acquire_apply_lock(client, "default", "my-pod")

        self.assertTrue(acquired)
        self.assertEqual(reason, "")

    def test_advisory_lock_force_overrides_other_host(self) -> None:
        """force=True acquires even when another host holds the lock."""
        client = MagicMock()
        client.execute.side_effect = [
            None,  # CREATE TABLE ON CLUSTER (ensure tracking table)
            None,  # INSERT lock row directly (no check with force=True)
        ]

        acquired, reason = acquire_apply_lock(client, "default", "my-pod", force=True)

        self.assertTrue(acquired)
        self.assertEqual(reason, "")
        # Two calls: CREATE ON CLUSTER + INSERT (via _record_step). No verify needed.
        self.assertEqual(client.execute.call_count, 2)

    @patch("posthog.clickhouse.migration_tools.tracking.time.sleep")
    def test_advisory_lock_race_detected(self, mock_sleep: MagicMock) -> None:
        """When two hosts both insert before replication, the loser backs off."""
        client = MagicMock()
        now = datetime.now(tz=UTC)
        client.execute.side_effect = [
            None,  # CREATE TABLE ON CLUSTER
            [],  # Check SELECT -- no lock (race window)
            None,  # INSERT lock row
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


if __name__ == "__main__":
    unittest.main()
