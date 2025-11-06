import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.conf import settings

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
        # :KLUDGE: Test setup does not create all kafka/mv tables
        self.assertEqual(len(out_of_sync_hosts), 1)

        out_of_sync_tables = next(iter(out_of_sync_hosts.values()))
        self.assertTrue(all("kafka" in table or "_mv" in table for table in out_of_sync_tables))

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
            from products.enterprise.backend.clickhouse.materialized_columns.columns import materialize
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
