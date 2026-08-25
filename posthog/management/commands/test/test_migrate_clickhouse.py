from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.management.commands.migrate_clickhouse import CLICKHOUSE_MIGRATIONS_TIMEOUT, Command


def _fake_client(node_count: int) -> tuple[MagicMock, list[str]]:
    executed: list[str] = []
    client = MagicMock()

    def execute(sql, *args, **kwargs):
        executed.append(sql)
        if "system.clusters" in sql:
            return [(node_count,)]
        return []

    client.execute.side_effect = execute
    context = MagicMock()
    context.__enter__.return_value = client
    return context, executed


class TestMigrateClickhouse(SimpleTestCase):
    @parameterized.expand([("multi_node", 2, True), ("single_node", 1, False)])
    @override_settings(MULTINODE_CLICKHOUSE=False)
    def test_tracking_table_precreate_follows_cluster_topology(
        self, _name: str, node_count: int, expect_precreate: bool
    ) -> None:
        # The pre-create must key on the real cluster topology, not on the
        # MULTINODE_CLICKHOUSE flag. Both cases run with the flag off.
        context, executed = _fake_client(node_count)
        with (
            patch("posthog.management.commands.migrate_clickhouse.default_client", return_value=context),
            patch("posthog.management.commands.migrate_clickhouse.Database"),
        ):
            Command().migrate("http://clickhouse", {"plan": False, "check": False, "fake": False, "upto": 99999})

        precreated = any(
            "infi_clickhouse_orm_migrations_distributed" in sql and "ON CLUSTER" in sql for sql in executed
        )
        self.assertEqual(precreated, expect_precreate)

    @override_settings(MULTINODE_CLICKHOUSE=False)
    def test_migration_connection_uses_generous_timeout(self) -> None:
        context, _ = _fake_client(node_count=1)
        with (
            patch("posthog.management.commands.migrate_clickhouse.default_client", return_value=context),
            patch("posthog.management.commands.migrate_clickhouse.Database") as database,
        ):
            Command().migrate("http://clickhouse", {"plan": False, "check": False, "fake": False, "upto": 99999})

        self.assertEqual(database.call_args.kwargs["timeout"], CLICKHOUSE_MIGRATIONS_TIMEOUT)
