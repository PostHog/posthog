from typing import Any
from uuid import uuid4

import pytest

from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import ALL_ASYNC_MIGRATIONS
from posthog.async_migrations.test.util import AsyncMigrationBaseTest
from posthog.models.async_migration import AsyncMigration, AsyncMigrationError, MigrationStatus
from posthog.settings import CLICKHOUSE_DATABASE

MIGRATION_NAME = "0002_events_sample_by"


def execute_query(query: str) -> Any:
    from posthog.client import sync_execute

    return sync_execute(query)


class Test0002EventsSampleBy(AsyncMigrationBaseTest):
    # This set up is necessary to mimic the state of the DB before the new default schema came into place
    def setUp(self):
        from ee.clickhouse.sql.events import EVENTS_TABLE_MV_SQL, KAFKA_EVENTS_TABLE_SQL

        super().setUp()
        self.create_events_table_query = execute_query(f"SHOW CREATE TABLE {CLICKHOUSE_DATABASE}.events")[0][0]

        # execute_query(f"ATTACH TABLE {CLICKHOUSE_DATABASE}.events_mv")
        Test0002EventsSampleBy.dropTables()

        execute_query(
            f"""
        CREATE TABLE {CLICKHOUSE_DATABASE}.events
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
        execute_query(KAFKA_EVENTS_TABLE_SQL())
        execute_query(EVENTS_TABLE_MV_SQL())

        execute_query(
            f"""
            INSERT INTO {CLICKHOUSE_DATABASE}.events (event, uuid, timestamp)
            VALUES
                ('event1', '{str(uuid4())}', now())
                ('event2', '{str(uuid4())}', now())
                ('event3', '{str(uuid4())}', now())
                ('event4', '{str(uuid4())}', now())
                ('event5', '{str(uuid4())}', '2019-01-01')
            """
        )

        definition = ALL_ASYNC_MIGRATIONS[MIGRATION_NAME]

        AsyncMigration.objects.get_or_create(
            name=MIGRATION_NAME,
            description=definition.description,
            posthog_min_version=definition.posthog_min_version,
            posthog_max_version=definition.posthog_max_version,
        )

    def tearDown(self):
        self.dropTables()
        execute_query(self.create_events_table_query)
        super().tearDown()

    @classmethod
    def dropTables(cls):
        execute_query(f"DROP TABLE IF EXISTS {CLICKHOUSE_DATABASE}.events_backup_0002_events_sample_by")
        execute_query(f"DROP TABLE IF EXISTS {CLICKHOUSE_DATABASE}.events_mv")
        execute_query(f"DROP TABLE IF EXISTS {CLICKHOUSE_DATABASE}.kafka_events")
        execute_query(f"DROP TABLE IF EXISTS {CLICKHOUSE_DATABASE}.events_failed")
        execute_query(f"DROP TABLE {CLICKHOUSE_DATABASE}.events")

    # Run the full migration through
    @pytest.mark.async_migrations
    def test_run_migration_in_full(self):
        from posthog.client import sync_execute

        migration_successful = start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)
        sm = AsyncMigration.objects.get(name=MIGRATION_NAME)

        self.assertTrue(migration_successful)
        self.assertEqual(sm.status, MigrationStatus.CompletedSuccessfully)
        self.assertEqual(sm.progress, 100)
        self.assertEqual(sm.current_operation_index, 9)
        errors = AsyncMigrationError.objects.filter(async_migration=sm)
        self.assertEqual(errors.count(), 0)

        create_table_res = sync_execute(f"SHOW CREATE TABLE {CLICKHOUSE_DATABASE}.events")
        events_count_res = sync_execute(f"SELECT COUNT(*) FROM {CLICKHOUSE_DATABASE}.events")
        backup_events_count_res = sync_execute(
            f"SELECT COUNT(*) FROM {CLICKHOUSE_DATABASE}.events_backup_0002_events_sample_by"
        )

        self.assertTrue(
            "ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))"
            in create_table_res[0][0]
        )

        self.assertEqual(events_count_res[0][0], 5)
        self.assertEqual(backup_events_count_res[0][0], 5)
