import importlib

from ee.clickhouse.materialized_columns.columns import materialize
from ee.clickhouse.util import ClickhouseDestroyTablesMixin, ClickhouseTestMixin
from posthog.client import sync_execute
from posthog.conftest import create_clickhouse_tables
from posthog.settings import CLICKHOUSE_DATABASE
from posthog.test.base import BaseTest

# Import the migration in this way because it starts with a number
_0026_fix_materialized_window_and_session_ids = importlib.import_module(
    "ee.clickhouse.migrations.0026_fix_materialized_window_and_session_ids"
)
does_column_exist = _0026_fix_materialized_window_and_session_ids.does_column_exist
materialize_session_and_window_id = _0026_fix_materialized_window_and_session_ids.materialize_session_and_window_id


class TestMigration(ClickhouseTestMixin, ClickhouseDestroyTablesMixin, BaseTest):
    def setUp(self):
        self.recreate_database()
        super().setUp()

        # Ideally, we would set this up by running the other migrations leading up
        # to this migrations, but it's very slow if we do that. So instead, we drop
        # the columns that this migration creates
        sync_execute("ALTER TABLE events DROP COLUMN $session_id")
        sync_execute("ALTER TABLE events DROP COLUMN $window_id")
        sync_execute("ALTER TABLE sharded_events DROP COLUMN $session_id")
        sync_execute("ALTER TABLE sharded_events DROP COLUMN $window_id")

    def tearDown(self):
        self.recreate_database()
        super().tearDown()

    def recreate_database(self):
        sync_execute(f"DROP DATABASE {CLICKHOUSE_DATABASE} SYNC")
        sync_execute(f"CREATE DATABASE {CLICKHOUSE_DATABASE}")
        create_clickhouse_tables(0)

    def assert_desired_state(self):
        self.assertTrue(does_column_exist(CLICKHOUSE_DATABASE, "events", "$session_id"))
        self.assertTrue(does_column_exist(CLICKHOUSE_DATABASE, "sharded_events", "$session_id"))
        self.assertTrue(does_column_exist(CLICKHOUSE_DATABASE, "events", "$window_id"))
        self.assertTrue(does_column_exist(CLICKHOUSE_DATABASE, "sharded_events", "$window_id"))

        self.assertFalse(does_column_exist(CLICKHOUSE_DATABASE, "events", "mat_$session_id"))
        self.assertFalse(does_column_exist(CLICKHOUSE_DATABASE, "sharded_events", "mat_$session_id"))
        self.assertFalse(does_column_exist(CLICKHOUSE_DATABASE, "events", "mat_$window_id"))
        self.assertFalse(does_column_exist(CLICKHOUSE_DATABASE, "sharded_events", "mat_$window_id"))

    def test_columns_already_materialized_prior_to_migration(self):
        materialize("events", "$session_id")
        materialize("events", "$window_id")

        materialize_session_and_window_id(CLICKHOUSE_DATABASE)
        self.assert_desired_state()

    def test_column_not_materialized_prior_to_migration(self):
        materialize_session_and_window_id(CLICKHOUSE_DATABASE)
        self.assert_desired_state()

    def test_sharded_events_columns_in_inconsistent_state(self):
        materialize("events", "$session_id")
        materialize("events", "$window_id")

        sync_execute("ALTER TABLE sharded_events RENAME COLUMN mat_$session_id TO $session_id")

        materialize_session_and_window_id(CLICKHOUSE_DATABASE)
        self.assert_desired_state()

    def test_events_columns_in_inconsistent_state(self):
        materialize("events", "$session_id")
        materialize("events", "$window_id")

        sync_execute("ALTER TABLE events RENAME COLUMN mat_$session_id TO $session_id")

        materialize_session_and_window_id(CLICKHOUSE_DATABASE)
        self.assert_desired_state()
