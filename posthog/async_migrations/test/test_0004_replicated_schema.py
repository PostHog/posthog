import re
from uuid import uuid4

import pytest
from django.conf import settings

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.sql.dead_letter_queue import KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL
from ee.clickhouse.sql.events import DISTRIBUTED_EVENTS_TABLE_SQL, KAFKA_EVENTS_TABLE_SQL
from ee.clickhouse.sql.groups import KAFKA_GROUPS_TABLE_SQL
from ee.clickhouse.sql.person import KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL, KAFKA_PERSONS_TABLE_SQL
from ee.clickhouse.sql.plugin_log_entries import KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL
from ee.clickhouse.sql.session_recording_events import KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_alter_queries
from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import get_async_migration_definition, setup_async_migrations
from posthog.conftest import create_clickhouse_tables
from posthog.test.base import BaseTest

MIGRATION_NAME = "0004_replicated_schema"


def _create_event(**kwargs):
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)


@pytest.mark.ee
class Test0004ReplicatedSchema(BaseTest, ClickhouseTestMixin):
    def setUp(self):
        self.recreate_database()
        sync_execute(KAFKA_EVENTS_TABLE_SQL())
        sync_execute(KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL())
        sync_execute(KAFKA_GROUPS_TABLE_SQL())
        sync_execute(KAFKA_PERSONS_TABLE_SQL())
        sync_execute(KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL())
        sync_execute(KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL())
        sync_execute(KAFKA_DEAD_LETTER_QUEUE_TABLE_SQL())

    def tearDown(self):
        self.recreate_database()

    def recreate_database(self):
        settings.CLICKHOUSE_REPLICATION = False
        sync_execute(f"DROP DATABASE {settings.CLICKHOUSE_DATABASE} SYNC")
        sync_execute(f"CREATE DATABASE {settings.CLICKHOUSE_DATABASE}")
        create_clickhouse_tables(0)

    def test_is_required(self):
        from ee.clickhouse.client import sync_execute

        migration = get_async_migration_definition(MIGRATION_NAME)

        self.assertTrue(migration.is_required())

        settings.CLICKHOUSE_REPLICATION = True
        sync_execute("DROP TABLE events SYNC")
        sync_execute(DISTRIBUTED_EVENTS_TABLE_SQL())
        self.assertFalse(migration.is_required())

    def test_migration(self):
        # :TRICKY: Relies on tables being migrated as unreplicated before.

        _create_event(team=self.team, distinct_id="test", event="$pageview")
        _create_event(team=self.team, distinct_id="test2", event="$pageview")

        settings.CLICKHOUSE_REPLICATION = True

        setup_async_migrations()
        migration_successful = start_async_migration(MIGRATION_NAME)
        self.assertTrue(migration_successful)

        self.verify_table_engines_correct()
        self.assertEqual(self.get_event_table_row_count(), 2)

    def verify_table_engines_correct(self):
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
            self.assert_correct_engine_type(name, engine)
            assert (name, self.sanitize(engine)) == self.snapshot

    def assert_correct_engine_type(self, name, engine):
        valid_engine = any(engine_type in engine for engine_type in ("Replicated", "Distributed", "Kafka"))
        assert valid_engine, f"Unexpected table engine for '{name}': {engine}"

    def get_event_table_row_count(self):
        return sync_execute("SELECT count() FROM events")[0][0]

    def sanitize(self, engine):
        return re.sub(r"/clickhouse/tables/[^_]+_", "/clickhouse/tables/", engine)
