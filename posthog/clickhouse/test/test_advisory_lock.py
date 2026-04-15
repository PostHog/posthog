"""Unit tests for advisory locking in tracking.py.

Tests acquire_apply_lock and release_apply_lock with mocked ClickHouse
client — no Django or ClickHouse connection required.
"""

from __future__ import annotations

from datetime import UTC, datetime

import unittest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

import posthog.clickhouse.test._stubs  # noqa: F401
from posthog.clickhouse.migration_tools.tracking import acquire_apply_lock, release_apply_lock


class TestAdvisoryLock(unittest.TestCase):
    """Tests for the advisory lock mechanism."""

    @patch("posthog.clickhouse.migration_tools.tracking.time.sleep")
    @parameterized.expand(
        [
            (
                "prevents_concurrent_apply",
                "other-pod",
                [
                    None,
                    [("other-pod", datetime.now(tz=UTC))],
                ],
                False,
                "other-pod",
                2,
            ),
            (
                "expired_allows_apply",
                "my-pod",
                [
                    None,
                    [],
                    None,
                    None,
                    [("my-pod", datetime.now(tz=UTC))],
                ],
                True,
                "",
                5,
            ),
            (
                "same_host_allows_reacquire",
                "my-pod",
                [
                    None,
                    [],
                    None,
                    None,
                    [("my-pod", datetime.now(tz=UTC))],
                ],
                True,
                "",
                5,
            ),
        ]
    )
    def test_advisory_lock_outcomes(
        self,
        _name: str,
        hostname: str,
        side_effect: list[object],
        expected_acquired: bool,
        expected_reason_fragment: str,
        expected_call_count: int,
        mock_sleep: MagicMock,
    ) -> None:
        client = MagicMock()
        client.execute.side_effect = side_effect

        acquired, reason = acquire_apply_lock(client, "default", hostname)

        self.assertEqual(acquired, expected_acquired)
        self.assertEqual(client.execute.call_count, expected_call_count)
        if expected_reason_fragment:
            self.assertIn(expected_reason_fragment, reason)
            self.assertIn("--force", reason)
        else:
            self.assertEqual(reason, "")
            mock_sleep.assert_not_called()
            sync_sql = client.execute.call_args_list[3].args[0]
            self.assertIn("SYSTEM SYNC REPLICA", sync_sql)
            self.assertIn("STRICT", sync_sql)
            verify_sql = client.execute.call_args_list[4].args[0]
            self.assertIn("ORDER BY applied_at ASC, host ASC", verify_sql)

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


if __name__ == "__main__":
    unittest.main()
