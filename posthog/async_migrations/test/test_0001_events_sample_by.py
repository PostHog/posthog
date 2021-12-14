from typing import Any

import pytest

from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import ALL_ASYNC_MIGRATIONS
from posthog.models.async_migration import AsyncMigration, MigrationStatus
from posthog.test.base import BaseTest

MIGRATION_NAME = "0001_events_sample_by"


def execute_query(query: str) -> Any:
    from ee.clickhouse.client import sync_execute

    return sync_execute(query)


class Test0001EventsSampleBy(BaseTest):

    # This set up is necessary to mimic the state of the DB before the new default schema came into place
    def setUp(self):
        from ee.clickhouse.sql.events import EVENTS_TABLE_MV_SQL, KAFKA_EVENTS_TABLE_SQL

        super().setUp()
        self.create_events_table_query = execute_query("SHOW CREATE TABLE events")[0][0]

        execute_query("DROP TABLE IF EXISTS events_mv")
        execute_query("DROP TABLE IF EXISTS kafka_events")
        execute_query("DROP TABLE events")

        execute_query(
            f"""
        CREATE TABLE events
        (
            `uuid` UUID,
            `event` String,
            `properties` String,
            `timestamp` DateTime64(6, 'UTC'),
            `team_id` Int64,
            `distinct_id` String,
            `elements_chain` String,
            `created_at` DateTime64(6, 'UTC'),
            `_timestamp` DateTime,
            `_offset` UInt64
        )
        ENGINE = ReplacingMergeTree(_timestamp)
        PARTITION BY toYYYYMM(timestamp)
        ORDER BY (team_id, toDate(timestamp), distinct_id, uuid)
        SETTINGS index_granularity = 8192               
        """
        )
        execute_query(KAFKA_EVENTS_TABLE_SQL)
        execute_query(EVENTS_TABLE_MV_SQL)

        definition = ALL_ASYNC_MIGRATIONS[MIGRATION_NAME]
        AsyncMigration.objects.get_or_create(
            name=MIGRATION_NAME,
            description=definition.description,
            posthog_min_version=definition.posthog_min_version,
            posthog_max_version=definition.posthog_max_version,
        )

    def tearDown(self):
        execute_query("DROP TABLE IF EXISTS events_mv")
        execute_query("DROP TABLE IF EXISTS kafka_events")
        execute_query("DROP TABLE events")
        execute_query(self.create_events_table_query)

    # Run the full migration through
    @pytest.mark.ee
    def test_run_migration_in_full(self):
        migration_successful = start_async_migration(MIGRATION_NAME)
        sm = AsyncMigration.objects.get(name=MIGRATION_NAME)

        from ee.clickhouse.client import sync_execute

        res = sync_execute("SHOW CREATE TABLE events")

        self.assertTrue("ORDER BY (team_id, toDate(timestamp), cityHash64(distinct_id), cityHash64(uuid))" in res[0][0])

        sm.refresh_from_db()

        self.assertTrue(migration_successful)

        self.assertEqual(sm.status, MigrationStatus.CompletedSuccessfully)
        self.assertEqual(sm.progress, 100)
        self.assertEqual(sm.last_error, "")
        self.assertEqual(sm.current_operation_index, 6)
