from datetime import datetime, timedelta
from uuid import UUID

import pytest

from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import get_async_migration_definition, setup_async_migrations
from posthog.async_migrations.test.util import AsyncMigrationBaseTest

MIGRATION_NAME = "0003_fill_person_distinct_id2"


@pytest.mark.ee
class Test0003FillPersonDistinctId2(AsyncMigrationBaseTest):
    def setUp(self):
        from posthog.client import sync_execute

        self.migration = get_async_migration_definition(MIGRATION_NAME)
        self.timestamp = 0
        sync_execute("TRUNCATE TABLE person_distinct_id")
        sync_execute("TRUNCATE TABLE person_distinct_id2")
        sync_execute("ALTER TABLE person_distinct_id COMMENT COLUMN distinct_id 'dont_skip_0003'")

    @pytest.mark.async_migrations
    def test_is_required(self):
        from posthog.client import sync_execute

        self.assertTrue(self.migration.is_required())

        sync_execute("ALTER TABLE person_distinct_id COMMENT COLUMN distinct_id 'skip_0003_fill_person_distinct_id2'")
        self.assertFalse(self.migration.is_required())

    @pytest.mark.async_migrations
    def test_migration(self):
        from posthog.client import sync_execute

        p1, p2, p3, p4, p5, p6 = [UUID(int=i) for i in range(6)]

        self.create_distinct_id(team_id=1, distinct_id="a", person_id=str(p1), sign=1)

        self.create_distinct_id(team_id=2, distinct_id="a", person_id=str(p2), sign=1)

        # Merged user
        self.create_distinct_id(team_id=2, distinct_id="b", person_id=str(p3), sign=1)
        self.create_distinct_id(team_id=2, distinct_id="b", person_id=str(p3), sign=-1)
        self.create_distinct_id(team_id=2, distinct_id="b", person_id=str(p4), sign=1)

        # Deleted user
        self.create_distinct_id(team_id=2, distinct_id="c", person_id=str(p5), sign=1)
        self.create_distinct_id(team_id=2, distinct_id="c", person_id=str(p5), sign=-1)

        self.create_distinct_id(team_id=3, distinct_id="d", person_id=str(p6), sign=1)

        setup_async_migrations(ignore_posthog_version=True)
        migration_successful = start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)
        self.assertTrue(migration_successful)

        rows = sync_execute(
            "SELECT team_id, distinct_id, person_id, version FROM person_distinct_id2 ORDER BY team_id, distinct_id"
        )

        self.assertEqual(rows, [(1, "a", p1, 0), (2, "a", p2, 0), (2, "b", p4, 0), (3, "d", p6, 0)])

    def create_distinct_id(self, **kwargs):
        from posthog.client import sync_execute

        sync_execute(
            "INSERT INTO person_distinct_id SELECT %(distinct_id)s, %(person_id)s, %(team_id)s, %(sign)s, %(timestamp)s, 0 VALUES",
            {**kwargs, "timestamp": datetime(2020, 1, 2) + timedelta(days=self.timestamp),},
        )
        self.timestamp += 1
