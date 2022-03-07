import pytest

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.person import COMMENT_DISTINCT_ID_COLUMN_SQL
from posthog.async_migrations.setup import ALL_ASYNC_MIGRATIONS
from posthog.settings import CLICKHOUSE_REPLICATION
from posthog.test.base import BaseTest


# Async migrations are data migrations aimed at getting users from an old schema to a new schema
# Fresh installs should have the new schema, however. So check that async migrations are being
# written correctly such that this is the case
#
# Note that 0004_replicated_schema is currently an exception for this
class TestAsyncMigrationsNotRequired(BaseTest):
    def setUp(self):
        sync_execute(COMMENT_DISTINCT_ID_COLUMN_SQL())

    def test_async_migrations_not_required_on_fresh_instances(self):

        for name, migration in ALL_ASYNC_MIGRATIONS.items():
            expected_is_required = name == "0004_replicated_schema" and not CLICKHOUSE_REPLICATION
            self.assertEqual(migration.is_required(), expected_is_required)
