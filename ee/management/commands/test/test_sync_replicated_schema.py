import pytest
from django.conf import settings

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.events import KAFKA_EVENTS_TABLE_SQL
from ee.clickhouse.sql.schema import CREATE_TABLE_QUERIES
from ee.clickhouse.util import ClickhouseTestMixin
from ee.management.commands.sync_replicated_schema import Command
from posthog.conftest import create_clickhouse_tables
from posthog.test.base import BaseTest


@pytest.mark.ee
class TestSyncReplicatedSchema(BaseTest, ClickhouseTestMixin):
    def setUp(self):
        settings.CLICKHOUSE_REPLICATION = True
        self.recreate_database()
        sync_execute(KAFKA_EVENTS_TABLE_SQL())

    def tearDown(self):
        self.recreate_database()
        settings.CLICKHOUSE_REPLICATION = False
        create_clickhouse_tables(0)

    def recreate_database(self):
        sync_execute(f"DROP DATABASE {settings.CLICKHOUSE_DATABASE} SYNC")
        sync_execute(f"CREATE DATABASE {settings.CLICKHOUSE_DATABASE}")

    def test_get_out_of_sync_hosts(self):
        # :KLUDGE: We simulate an out-of-sync database by wiping everything but one table
        out_of_sync_hosts = Command().get_out_of_sync_hosts()

        self.assertEqual(len(out_of_sync_hosts), 1)

        [values] = list(out_of_sync_hosts.values())
        self.assertEqual(len(values), len(CREATE_TABLE_QUERIES) - 1)

    def test_handle_sync(self):
        Command().handle()

        self.assertEqual(len(Command().get_out_of_sync_hosts()), 0)

    def test_handle_not_replicated_does_nothing(self):
        settings.CLICKHOUSE_REPLICATION = False

        Command().handle()
        self.assertEqual(len(Command().get_out_of_sync_hosts()), 1)
