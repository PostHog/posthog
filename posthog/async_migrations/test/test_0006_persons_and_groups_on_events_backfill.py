import json
import re

import pytest
from django.conf import settings
from django.test import override_settings

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

MIGRATION_NAME = "0006_persons_and_groups_on_events_backfill"

def run_migration():
    setup_async_migrations(ignore_posthog_version=True)
    return start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)


@pytest.mark.async_migrations
class Test0006PersonsAndGroupsOnEventsBackfill(AsyncMigrationBaseTest, ClickhouseTestMixin):
    def setUp(self):
        self.clear_tables()
        super().setUp()

    def tearDown(self):
        self.clear_tables()
        super().tearDown()

    def clear_tables(self):
        sync_execute("DROP TABLE IF EXISTS tmp_person_0006")
        sync_execute("DROP TABLE IF EXISTS tmp_person_distinct_id2_0006")
        sync_execute("DROP TABLE IF EXISTS tmp_groups_0006")

    def test_is_required_without_compression(self):
        pass

    def test_is_not_required_by_default(self):
        pass

    def test_completes_successfully(self):
        self.assertTrue(run_migration())

    def test_data_copy_persons(self):
        pass

    def test_duplicated_data_persons(self):
        # Assert count in temporary tables.
        pass

    def test_data_copy_groups(self):
        pass

    def test_disk_usage_low(self):
        pass

    def test_rollback(self):
        pass
