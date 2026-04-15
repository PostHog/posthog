"""Unit tests for runner.execute_migration_step routing logic."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from posthog.clickhouse.migration_tools.manifest import ManifestStep


class TestExecuteMigrationStepRouting(unittest.TestCase):
    """Verify that execute_migration_step calls the right cluster method."""

    def _make_step(self, *, sharded: bool = False, is_alter_on_replicated: bool = False) -> ManifestStep:
        return ManifestStep(
            sql="_reconcile:create_t",
            node_roles=["ALL"],
            comment="test step",
            sharded=sharded,
            is_alter_on_replicated_table=is_alter_on_replicated,
        )

    def _run(self, step: ManifestStep) -> MagicMock:
        cluster = MagicMock()
        future = MagicMock()
        future.result.return_value = {}
        cluster.map_one_host_per_shard.return_value = future
        cluster.any_host_by_roles.return_value = future
        cluster.map_hosts_by_roles.return_value = future

        with patch("posthog.clickhouse.migration_tools.runner._map_node_roles", return_value=[]):
            from posthog.clickhouse.migration_tools.runner import execute_migration_step

            execute_migration_step(cluster, step, "CREATE TABLE t ...")

        return cluster

    def test_sharded_alter_replicated_uses_one_host_per_shard(self):
        step = self._make_step(sharded=True, is_alter_on_replicated=True)
        cluster = self._run(step)
        cluster.map_one_host_per_shard.assert_called_once()
        cluster.any_host_by_roles.assert_not_called()
        cluster.map_hosts_by_roles.assert_not_called()

    def test_alter_replicated_only_uses_any_host(self):
        step = self._make_step(sharded=False, is_alter_on_replicated=True)
        cluster = self._run(step)
        cluster.any_host_by_roles.assert_called_once()
        cluster.map_one_host_per_shard.assert_not_called()
        cluster.map_hosts_by_roles.assert_not_called()

    def test_regular_step_uses_map_hosts_by_roles(self):
        step = self._make_step(sharded=False, is_alter_on_replicated=False)
        cluster = self._run(step)
        cluster.map_hosts_by_roles.assert_called_once()
        cluster.map_one_host_per_shard.assert_not_called()
        cluster.any_host_by_roles.assert_not_called()


class TestMapNodeRoles(unittest.TestCase):
    def test_unknown_role_raises(self):
        from posthog.clickhouse.migration_tools.runner import _map_node_roles

        with self.assertRaises(ValueError) as ctx:
            _map_node_roles(["UNKNOWN_ROLE"])
        self.assertIn("UNKNOWN_ROLE", str(ctx.exception))
