import json
import re

import pytest
from django.conf import settings

from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import (
    get_async_migration_definition,
    reload_migration_definitions,
    setup_async_migrations,
)
from posthog.async_migrations.test.util import AsyncMigrationBaseTest
from posthog.client import query_with_columns, sync_execute
from posthog.models.async_migration import AsyncMigration, MigrationStatus
from posthog.models.person import Person
from posthog.models.person.sql import KAFKA_PERSONS_TABLE_SQL, PERSONS_TABLE_MV_SQL, PERSONS_TABLE_SQL
from posthog.models.signals import mute_selected_signals
from posthog.redis import get_client
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
        reload_migration_definitions()
        get_client().delete("posthog.async_migrations.0005.highwatermark")

        sync_execute("DROP TABLE IF EXISTS person_backup_0005_person_collapsed_by_version")
        sync_execute("DROP TABLE IF EXISTS person_failed_person_collapsed_by_version")
        sync_execute("DROP TABLE IF EXISTS tmp_person_mv_0005_person_collapsed_by_version")
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

    def test_migration_data_copying(self):
        # Set up some persons both in clickhouse and postgres
        p1 = Person.objects.create(
            team=self.team, properties={"prop": 1}, version=1, is_identified=False, created_at="2022-01-04T12:00:00Z",
        )
        p2 = Person.objects.create(
            team=self.team, properties={"prop": 2}, version=2, is_identified=True, created_at="2022-02-04T12:00:00Z",
        )

        # Set up some persons out of sync in clickhouse
        with mute_selected_signals():
            p3 = Person.objects.create(
                team=self.team,
                properties={"prop": 3},
                version=3,
                is_identified=False,
                created_at="2022-03-04T12:00:00Z",
            )
            p4 = Person.objects.create(
                team=self.team,
                properties={"prop": 4},
                version=4,
                is_identified=True,
                created_at="2022-04-04T12:00:00Z",
            )

        self.assertEqual(len(self.get_clickhouse_persons()), 2)

        setup_async_migrations(ignore_posthog_version=True)
        migration_successful = start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)
        self.assertTrue(migration_successful)

        clickhouse_persons = self.get_clickhouse_persons()
        self.assertEqual(len(clickhouse_persons), 4)
        for pg_person, clickhouse_person in zip([p1, p2, p3, p4], clickhouse_persons):
            self.verify_person_matches(pg_person, clickhouse_person)

    def test_rollbacks(self):
        setup_async_migrations(ignore_posthog_version=True)
        migration = get_async_migration_definition(MIGRATION_NAME)

        migration.operations[-1].fn = lambda _: 0 / 0  # type: ignore

        migration_successful = start_async_migration(MIGRATION_NAME)
        self.assertFalse(migration_successful)
        self.assertEqual(AsyncMigration.objects.get(name=MIGRATION_NAME).status, MigrationStatus.RolledBack)

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

    def get_clickhouse_persons(self):
        return query_with_columns("SELECT * FROM person FINAL ORDER BY version")

    def verify_person_matches(self, pg_person, clickhouse_person):
        self.assertEqual(pg_person.version, clickhouse_person["version"])
        self.assertEqual(str(pg_person.uuid), str(clickhouse_person["id"]))
        self.assertEqual(pg_person.properties, json.loads(clickhouse_person["properties"]))
        self.assertEqual(pg_person.is_identified, bool(clickhouse_person["is_identified"]))
        self.assertEqual(pg_person.team_id, clickhouse_person["team_id"])
        self.assertEqual(
            pg_person.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            clickhouse_person["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.assertEqual(clickhouse_person["is_deleted"], 0)
