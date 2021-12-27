import pytest

from posthog.async_migrations.setup import get_async_migration_definition
from posthog.test.base import BaseTest

MIGRATION_NAME = "0003_fill_person_distinct_id2"


@pytest.mark.ee
class Test0003FillPersonDistinctId2(BaseTest):
    def setUp(self):
        self.migration = get_async_migration_definition(MIGRATION_NAME)

    def test_is_required(self):
        from ee.clickhouse.client import sync_execute

        sync_execute("ALTER TABLE person_distinct_id COMMENT COLUMN distinct_id ''")
        self.assertTrue(self.migration.is_required())

        sync_execute("ALTER TABLE person_distinct_id COMMENT COLUMN distinct_id 'skip_0003_fill_person_distinct_id2'")
        self.assertFalse(self.migration.is_required())
