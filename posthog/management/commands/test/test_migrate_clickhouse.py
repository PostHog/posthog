from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.management.commands.migrate_clickhouse import Command


class TestMigrateClickhouse(SimpleTestCase):
    @patch("posthog.management.commands.migrate_clickhouse.CLICKHOUSE_SATELLITE_CLUSTERS", ["ai_events", "sessions"])
    @patch("posthog.management.commands.migrate_clickhouse.CLICKHOUSE_MIGRATIONS_CLUSTER", "posthog_migrations")
    @patch.object(Command, "_should_bootstrap_databases", return_value=True)
    @patch("posthog.management.commands.migrate_clickhouse.default_client")
    def test_create_database_covers_migrations_and_satellite_clusters(self, mock_default_client, _mock_should):
        client = MagicMock()
        mock_default_client.return_value.__enter__.return_value = client

        Command()._create_database_if_not_exists("posthog")

        executed = [call.args[0] for call in client.execute.call_args_list]
        assert executed == [
            "CREATE DATABASE IF NOT EXISTS posthog ON CLUSTER posthog_migrations",
            "CREATE DATABASE IF NOT EXISTS posthog ON CLUSTER ai_events",
            "CREATE DATABASE IF NOT EXISTS posthog ON CLUSTER sessions",
        ]

    @parameterized.expand(
        [
            # (name, TEST, E2E_TESTING, DEBUG, CLOUD_DEPLOYMENT, MULTINODE_CLICKHOUSE, expected)
            ("cloud_prod", False, False, False, "US", False, True),
            ("multinode_smoke", False, False, True, "", True, True),
            ("test_run", True, False, True, "", False, True),
            ("e2e", False, True, True, "", False, True),
            ("local_hobby", False, False, True, "", False, False),
        ]
    )
    def test_should_bootstrap_databases(self, _name, test, e2e, debug, cloud, multinode, expected):
        with override_settings(
            TEST=test,
            E2E_TESTING=e2e,
            DEBUG=debug,
            CLOUD_DEPLOYMENT=cloud,
            MULTINODE_CLICKHOUSE=multinode,
        ):
            assert Command()._should_bootstrap_databases() is expected
