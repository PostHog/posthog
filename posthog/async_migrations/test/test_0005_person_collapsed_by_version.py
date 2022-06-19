import re
from uuid import uuid4

import pytest
from django.conf import settings

from posthog.async_migrations.setup import get_async_migration_definition
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
