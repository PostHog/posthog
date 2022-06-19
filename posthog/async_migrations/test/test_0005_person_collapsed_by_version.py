import re

import pytest
from django.conf import settings

from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import get_async_migration_definition, setup_async_migrations
from posthog.async_migrations.test.util import AsyncMigrationBaseTest
from posthog.client import sync_execute
from posthog.models.person.sql import KAFKA_PERSONS_TABLE_SQL, PERSONS_TABLE_MV_SQL, PERSONS_TABLE_SQL
from posthog.test.base import ClickhouseTestMixin

MIGRATION_NAME = "0005_person_collapsed_by_version"

ORIGINAL_TABLE_SQL = f"""
CREATE TABLE posthog_test.person ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'
(
    `id` UUID,
    `created_at` DateTime64(3),
    `team_id` Int64,
    `properties` String,
    `is_identified` Int8,
    `is_deleted` Int8 DEFAULT 0,
    `version` UInt64,
    `_timestamp` DateTime,
    `_offset` UInt64
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{{uuid}}-noshard/posthog.person', '{{replica}}-{{shard}}', _timestamp)
ORDER BY (team_id, id)
SETTINGS index_granularity = 819
"""


@pytest.mark.async_migrations
class Test0005PersonCollapsedByVersion(AsyncMigrationBaseTest, ClickhouseTestMixin):
    def setUp(self):
        self.recreate_person_table()
        super().setUp()

    def tearDown(self):
        self.recreate_person_table()
        super().tearDown()

    def recreate_person_table(self, sql=ORIGINAL_TABLE_SQL):
        sync_execute("DROP TABLE IF EXISTS person_backup_0005_person_collapsed_by_version")
        sync_execute("DROP TABLE IF EXISTS person_failed_person_collapsed_by_version")
        sync_execute("DROP TABLE IF EXISTS person")
        sync_execute("DROP TABLE IF EXISTS person_mv")
        sync_execute("DROP TABLE IF EXISTS kafka_person")
        sync_execute(sql)
        sync_execute(KAFKA_PERSONS_TABLE_SQL())
        sync_execute(PERSONS_TABLE_MV_SQL)

    def test_is_required(self):
        migration = get_async_migration_definition(MIGRATION_NAME)

        self.assertTrue(migration.is_required())

        self.recreate_person_table(PERSONS_TABLE_SQL())
        self.assertFalse(migration.is_required())

    def test_migration_schema(self):
        setup_async_migrations(ignore_posthog_version=True)
        migration_successful = start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)
        self.assertTrue(migration_successful)

        self.verify_table_schema()

    def verify_table_schema(self):
        table_results = sync_execute(
            """
            SELECT name
            FROM system.tables
            WHERE database = %(database)s
              AND name LIKE '%%person%%'
              -- Ignore unrelated tables
              AND name NOT LIKE '%%distinct_id%%'
              AND name NOT LIKE '%%cohort%%'
            ORDER BY name
            """,
            {"database": settings.CLICKHOUSE_DATABASE},
        )
        table_results = [row[0] for row in table_results]

        self.assertEqual(
            table_results, ["kafka_person", "person", "person_backup_0005_person_collapsed_by_version", "person_mv"],
        )
        for name in table_results:
            create_table_query = sync_execute(f"SHOW CREATE TABLE {name}")[0][0]
            assert self.sanitize(create_table_query) == self.snapshot

    def sanitize(self, create_table_query):
        create_table_query = re.sub(
            r"/clickhouse/tables/am0005_\d+", "/clickhouse/tables/am0005_20220601000000", create_table_query
        )
        create_table_query = re.sub(
            r"/clickhouse/tables/[-0-9a-f]+-noshard",
            "/clickhouse/tables/00000000-0000-0000-0000-000000000000-noshard",
            create_table_query,
        )
        return create_table_query
