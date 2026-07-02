import pytest

from posthog.async_migrations.setup import ALL_ASYNC_MIGRATIONS
from posthog.async_migrations.test.util import AsyncMigrationBaseTest
from posthog.clickhouse.client import sync_execute
from posthog.models.person.sql import COMMENT_DISTINCT_ID_COLUMN_SQL

pytestmark = pytest.mark.async_migrations


# Async migrations are data migrations aimed at getting users from an old schema to a new schema
# Fresh installs should have the new schema, however. So check that async migrations are being
# written correctly such that this is the case
#
# Note that 0004_replicated_schema is currently an exception for this
class TestAsyncMigrationsNotRequired(AsyncMigrationBaseTest):
    def setUp(self):
        sync_execute(COMMENT_DISTINCT_ID_COLUMN_SQL())
        sync_execute("TRUNCATE TABLE sharded_events")

    def test_async_migrations_not_required_on_fresh_instances(self):
        for name, migration in ALL_ASYNC_MIGRATIONS.items():
            self.assertFalse(
                migration.is_required(),
                f"Async migration {name} is_required returned True",
            )
