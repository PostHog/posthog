import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.conftest import create_clickhouse_tables
from posthog.management.commands.sync_replicated_schema import Command


@pytest.mark.ee
class TestSyncReplicatedSchema(BaseTest, ClickhouseTestMixin):
    def tearDown(self):
        self.recreate_database()
        super().tearDown()

    def recreate_database(self, create_tables=True):
        sync_execute(f"DROP DATABASE {settings.CLICKHOUSE_DATABASE} SYNC")
        sync_execute(f"CREATE DATABASE {settings.CLICKHOUSE_DATABASE}")
        if create_tables:
            create_clickhouse_tables()

    def test_analyze_test_cluster(self):
        self.recreate_database(create_tables=True)
        (
            host_tables,
            create_table_queries,
            out_of_sync_hosts,
        ) = Command().analyze_cluster_tables()

        self.assertEqual(len(host_tables), 1)
        self.assertGreater(len(create_table_queries), 0)
        self.assertEqual(out_of_sync_hosts, {})

    def test_analyze_empty_cluster(self):
        self.recreate_database(create_tables=False)

        (
            host_tables,
            create_table_queries,
            out_of_sync_hosts,
        ) = Command().analyze_cluster_tables()

        self.assertEqual(host_tables, {})
        self.assertEqual(create_table_queries, {})
        self.assertEqual(out_of_sync_hosts, {})

    def test_create_missing_tables(self):
        try:
            from ee.clickhouse.materialized_columns.columns import materialize
        except ImportError:
            pass
        else:
            self.recreate_database(create_tables=True)
            materialize("events", "some_property")
            _, create_table_queries, _ = Command().analyze_cluster_tables()
            sync_execute("DROP TABLE sharded_events SYNC")

            self.assertIn("mat_some_property", create_table_queries["sharded_events"])
            Command().create_missing_tables({"test_host": {"sharded_events"}}, create_table_queries)

            schema = sync_execute("SHOW CREATE TABLE sharded_events")[0][0]
            self.assertIn("mat_some_property", schema)


class TestSyncReplicatedSchemaPlanning(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "role_scoped_view_not_expected_on_other_roles",
                {"data1": {"events"}, "medium1": {"writable_events", "events_mv"}},
                {"data1": "data", "medium1": "medium"},
                {},
            ),
            (
                "new_host_missing_tables_of_its_role",
                {"medium1": {"writable_events", "events_mv"}, "medium2": {"writable_events"}, "data1": {"events"}},
                {"data1": "data", "medium1": "medium", "medium2": "medium"},
                {"medium2": {"events_mv"}},
            ),
            (
                "hosts_without_role_macro_share_one_group",
                {"host1": {"events", "sessions"}, "host2": {"events"}},
                {},
                {"host2": {"sessions"}},
            ),
        ]
    )
    def test_get_out_of_sync_hosts(self, _name, host_tables, host_roles, expected):
        self.assertEqual(Command().get_out_of_sync_hosts(host_tables, host_roles), expected)

    @patch("posthog.management.commands.sync_replicated_schema.sync_execute")
    def test_create_missing_tables_skips_views_and_dictionaries(self, mock_sync_execute):
        create_table_queries = {
            "sharded_events": "CREATE TABLE posthog.sharded_events (uuid UUID) ENGINE = MergeTree ORDER BY uuid",
            "events_mv": "CREATE MATERIALIZED VIEW posthog.events_mv TO posthog.writable_events AS SELECT 1",
            "sessions_v": "CREATE VIEW posthog.sessions_v AS SELECT 1",
            "groups_dict": "CREATE DICTIONARY posthog.groups_dict (id UInt64) PRIMARY KEY id",
        }

        Command().create_missing_tables({"host2": set(create_table_queries)}, create_table_queries)

        executed = [call.args[0] for call in mock_sync_execute.call_args_list]
        self.assertEqual(
            executed,
            [
                f"CREATE TABLE IF NOT EXISTS posthog.sharded_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}' "
                "(uuid UUID) ENGINE = MergeTree ORDER BY uuid"
            ],
        )
