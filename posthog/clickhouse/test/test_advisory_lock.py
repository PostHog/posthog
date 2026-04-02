"""Unit tests for advisory locking in tracking.py.

Tests acquire_apply_lock and release_apply_lock with mocked ClickHouse
client — no Django or ClickHouse connection required.
"""

from __future__ import annotations

from datetime import UTC, datetime

import unittest
from unittest.mock import MagicMock

import posthog.clickhouse.test._stubs  # noqa: F401
from posthog.clickhouse.migration_tools.tracking import acquire_apply_lock, release_apply_lock


class TestAdvisoryLock(unittest.TestCase):
    """Tests for the advisory lock mechanism."""

    def test_advisory_lock_prevents_concurrent_apply(self) -> None:
        """An active lock from another host prevents acquisition."""
        client = MagicMock()
        now = datetime.now(tz=UTC)
        # Atomic pattern: ensure table, INSERT...SELECT WHERE NOT EXISTS, verify SELECT
        client.execute.side_effect = [
            None,  # CREATE TABLE IF NOT EXISTS (ensure tracking table)
            None,  # INSERT...SELECT WHERE NOT EXISTS (atomic — no rows inserted due to existing lock)
            [("other-pod", now)],  # Verify SELECT — another host holds the lock
        ]

        acquired, reason = acquire_apply_lock(client, "default", "my-pod")

        self.assertFalse(acquired)
        self.assertIn("other-pod", reason)
        self.assertIn("--force", reason)

    def test_advisory_lock_expired_allows_apply(self) -> None:
        """No active lock (expired or absent) allows acquisition."""
        client = MagicMock()
        now = datetime.now(tz=UTC)
        client.execute.side_effect = [
            None,  # CREATE TABLE IF NOT EXISTS (ensure tracking table)
            None,  # INSERT...SELECT WHERE NOT EXISTS (atomic — row inserted)
            [("my-pod", now)],  # Verify SELECT — our lock is latest
        ]

        acquired, reason = acquire_apply_lock(client, "default", "my-pod")

        self.assertTrue(acquired)
        self.assertEqual(reason, "")
        # Three calls: CREATE IF NOT EXISTS + INSERT...SELECT + verify SELECT
        self.assertEqual(client.execute.call_count, 3)

    def test_advisory_lock_same_host_allows_reacquire(self) -> None:
        """A lock from the same host allows re-acquisition (idempotent)."""
        client = MagicMock()
        now = datetime.now(tz=UTC)
        client.execute.side_effect = [
            None,  # CREATE TABLE IF NOT EXISTS (ensure tracking table)
            None,  # INSERT...SELECT WHERE NOT EXISTS (atomic)
            [("my-pod", now)],  # Verify SELECT — our own host holds the lock
        ]

        acquired, reason = acquire_apply_lock(client, "default", "my-pod")

        self.assertTrue(acquired)
        self.assertEqual(reason, "")

    def test_advisory_lock_force_overrides_other_host(self) -> None:
        """force=True acquires even when another host holds the lock."""
        client = MagicMock()
        client.execute.side_effect = [
            None,  # CREATE TABLE IF NOT EXISTS (ensure tracking table)
            None,  # INSERT lock row directly (no atomic check with force=True)
        ]

        acquired, reason = acquire_apply_lock(client, "default", "my-pod", force=True)

        self.assertTrue(acquired)
        self.assertEqual(reason, "")
        # Two calls: CREATE IF NOT EXISTS + INSERT (via _record_step). No verify needed.
        self.assertEqual(client.execute.call_count, 2)

    def test_release_apply_lock_inserts_shadow_row(self) -> None:
        """Release inserts a success=False row to shadow the lock."""
        client = MagicMock()
        client.execute.return_value = None

        release_apply_lock(client, "default", "my-pod")

        # Should have inserted a row (via _record_step which calls client.execute)
        client.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
