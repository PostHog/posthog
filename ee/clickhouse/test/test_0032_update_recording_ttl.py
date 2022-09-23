import importlib

from posthog.client import sync_execute
from posthog.conftest import create_clickhouse_tables
from posthog.models.instance_setting import set_instance_setting
from posthog.models.session_recording_event.sql import SESSION_RECORDING_EVENTS_DATA_TABLE
from posthog.settings import CLICKHOUSE_DATABASE
from posthog.test.base import BaseTest, ClickhouseDestroyTablesMixin, ClickhouseTestMixin

# Import the migration in this way because it starts with a number
_0032_update_recording_ttl = importlib.import_module("posthog.clickhouse.migrations.0032_update_recording_ttl")
update_recordings_ttl = _0032_update_recording_ttl.update_recordings_ttl


class TestMigration(ClickhouseTestMixin, ClickhouseDestroyTablesMixin, BaseTest):
    def setUp(self):
        self.recreate_database()
        super().setUp()

    def tearDown(self):
        self.recreate_database()
        super().tearDown()

    def check_ttl(self, weeks):
        result = sync_execute(f"SHOW CREATE TABLE {SESSION_RECORDING_EVENTS_DATA_TABLE()}")
        expected_ttl = f"TTL toDate(timestamp) + toIntervalWeek({weeks})"
        self.assertIn(expected_ttl, result[0][0])

    def recreate_database(self):
        sync_execute(f"DROP DATABASE {CLICKHOUSE_DATABASE} SYNC")
        sync_execute(f"CREATE DATABASE {CLICKHOUSE_DATABASE}")
        create_clickhouse_tables(0)

    def test_default_ttl(self):
        self.check_ttl(3)

    def test_ttl_with_custom_ttl_setting(self):
        set_instance_setting("RECORDINGS_TTL_WEEKS", 5)
        update_recordings_ttl(CLICKHOUSE_DATABASE)
        self.check_ttl(5)
