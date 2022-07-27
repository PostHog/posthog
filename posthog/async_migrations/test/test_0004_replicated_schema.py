import re
from uuid import uuid4

import pytest
from django.conf import settings

from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import get_async_migration_definition, setup_async_migrations
from posthog.async_migrations.test.util import AsyncMigrationBaseTest
from posthog.clickhouse.dead_letter_queue import KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL
from posthog.clickhouse.plugin_log_entries import KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL
from posthog.client import sync_execute
from posthog.conftest import create_clickhouse_tables
from posthog.models.async_migration import AsyncMigration, MigrationStatus
from posthog.models.event.sql import DISTRIBUTED_EVENTS_TABLE_SQL, KAFKA_EVENTS_TABLE_SQL
from posthog.models.event.util import create_event
from posthog.models.group.sql import KAFKA_GROUPS_TABLE_SQL
from posthog.models.person.sql import KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL, KAFKA_PERSONS_TABLE_SQL
from posthog.models.session_recording_event.sql import KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL
from posthog.test.base import ClickhouseTestMixin

MIGRATION_NAME = "0004_replicated_schema"


def _create_event(**kwargs):
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)


class Test0004ReplicatedSchema(AsyncMigrationBaseTest, ClickhouseTestMixin):
    def setUp(self):
        self.recreate_database(replication=False)
        sync_execute(KAFKA_EVENTS_TABLE_SQL())
        sync_execute(KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL())
        sync_execute(KAFKA_GROUPS_TABLE_SQL())
        sync_execute(KAFKA_PERSONS_TABLE_SQL())
        sync_execute(KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL())
        sync_execute(KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL())
        sync_execute(KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL())

    def tearDown(self):
        self.recreate_database(replication=True)
        super().tearDown()

    def recreate_database(self, replication: bool):
        settings.CLICKHOUSE_REPLICATION = replication
        sync_execute(f"DROP DATABASE {settings.CLICKHOUSE_DATABASE} SYNC")
        sync_execute(f"CREATE DATABASE {settings.CLICKHOUSE_DATABASE}")
        create_clickhouse_tables(0)

    @pytest.mark.async_migrations
    def test_is_required(self):
        from posthog.client import sync_execute

        migration = get_async_migration_definition(MIGRATION_NAME)

        self.assertTrue(migration.is_required())

        settings.CLICKHOUSE_REPLICATION = True
        sync_execute("DROP TABLE events SYNC")
        sync_execute(DISTRIBUTED_EVENTS_TABLE_SQL())
        self.assertFalse(migration.is_required())

    @pytest.mark.async_migrations
    def test_migration(self):
        # :TRICKY: Relies on tables being migrated as unreplicated before.

        _create_event(team=self.team, distinct_id="test", event="$pageview")
        _create_event(team=self.team, distinct_id="test2", event="$pageview")

        settings.CLICKHOUSE_REPLICATION = True

        setup_async_migrations(ignore_posthog_version=True)
        migration_successful = start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)
        self.assertTrue(migration_successful)

        self.verify_table_engines_correct(
            expected_engine_types=(
                "ReplicatedReplacingMergeTree",
                "ReplicatedCollapsingMergeTree",
                "Distributed",
                "Kafka",
            )
        )
        self.assertEqual(self.get_event_table_row_count(), 2)

    @pytest.mark.async_migrations
    def test_rollback(self):
        # :TRICKY: Relies on tables being migrated as unreplicated before.

        _create_event(team=self.team, distinct_id="test", event="$pageview")
        _create_event(team=self.team, distinct_id="test2", event="$pageview")

        settings.CLICKHOUSE_REPLICATION = True

        setup_async_migrations(ignore_posthog_version=True)
        migration = get_async_migration_definition(MIGRATION_NAME)

        self.assertEqual(len(migration.operations), 57)
        migration.operations[31].sql = "THIS WILL FAIL!"  # type: ignore

        migration_successful = start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)
        self.assertFalse(migration_successful)
        self.assertEqual(AsyncMigration.objects.get(name=MIGRATION_NAME).status, MigrationStatus.RolledBack)

        self.verify_table_engines_correct(expected_engine_types=("ReplacingMergeTree", "CollapsingMergeTree", "Kafka"))

    def verify_table_engines_correct(self, expected_engine_types):
        table_engines = sync_execute(
            """
            SELECT name, engine_full
            FROM system.tables
            WHERE database = %(database)s
              -- Ignore backup tables
              AND name NOT LIKE '%%backup_0004%%'
              -- Ignore materialized views
              AND engine_full != ''
              -- Ignore old tables
              AND name != 'person_distinct_id'
            ORDER BY name
            """,
            {"database": settings.CLICKHOUSE_DATABASE},
        )

        for name, engine in table_engines:
            self.assert_correct_engine_type(name, engine, expected_engine_types)
            assert (name, self.sanitize(engine)) == self.snapshot

    def assert_correct_engine_type(self, name, engine, expected_engine_types):
        valid_engine = any(engine.startswith(engine_type) for engine_type in expected_engine_types)
        assert valid_engine, f"Unexpected table engine for '{name}': {engine}"

    def get_event_table_row_count(self):
        return sync_execute("SELECT count() FROM events")[0][0]

    def sanitize(self, engine):
        return re.sub(r"/clickhouse/tables/am0004_\d+", "/clickhouse/tables/am0004_20220201000000", engine)
