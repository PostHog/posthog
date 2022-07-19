import pytest

from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import (
    get_async_migration_definition,
    reload_migration_definitions,
    setup_async_migrations,
)
from posthog.async_migrations.test.util import AsyncMigrationBaseTest
from posthog.async_migrations.utils import execute_op_postgres
from posthog.models import Dashboard, DashboardTile, Insight
from posthog.redis import get_client

MIGRATION_NAME = "0006_generate_dashboard_tile_filters_hashes"


@pytest.mark.async_migrations
class Test0006GenerateDashboardTilesFiltersHashes(AsyncMigrationBaseTest):
    def setUp(self):
        reload_migration_definitions()
        get_client().delete("posthog.async_migrations.0006.highwatermark")
        super().setUp()

    def tearDown(self):
        super().tearDown()

    def test_is_required(self):
        dashboard = Dashboard.objects.create(team=self.team, name="a dashboard")
        insight = Insight.objects.create(team=self.team, name="an insight", filters={"events": [{"id": "$pageview"}],})

        self.assertEqual(0, DashboardTile.objects.filter(filters_hash=None).count())

        migration = get_async_migration_definition(MIGRATION_NAME)

        self.assertFalse(migration.is_required())

        self._create_tile_with_no_filters_hash(dashboard, insight)
        self.assertEqual(1, DashboardTile.objects.filter(filters_hash=None).count())
        self.assertTrue(migration.is_required())

    def test_filters_hashes_are_populated(self):
        dashboard: Dashboard = Dashboard.objects.create(team=self.team, name="for the type checker")
        for i in range(102):  # force the processing to page
            if i % 10 == 0:
                dashboard = Dashboard.objects.create(team=self.team, name=i)

            insight = Insight.objects.create(team=self.team, name=i, filters={"events": [{"id": "$pageview"}],})
            self._create_tile_with_no_filters_hash(dashboard, insight)

        setup_async_migrations(ignore_posthog_version=True)
        migration_successful = start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)

        self.assertTrue(migration_successful)
        self.assertEqual(0, DashboardTile.objects.filter(filters_hash=None).count())

    # def test_migration_schema(self):
    #     setup_async_migrations(ignore_posthog_version=True)
    #     migration_successful = start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)
    #     self.assertTrue(migration_successful)
    #
    #     self.verify_table_schema()
    #
    # def test_migration_data_copying(self):
    #     # Set up some persons both in clickhouse and postgres
    #     p1 = Person.objects.create(
    #         team=self.team, properties={"prop": 1}, version=1, is_identified=False, created_at="2022-01-04T12:00:00Z",
    #     )
    #     p2 = Person.objects.create(
    #         team=self.team, properties={"prop": 2}, version=2, is_identified=True, created_at="2022-02-04T12:00:00Z",
    #     )
    #
    #     # Set up some persons out of sync in clickhouse
    #     with mute_selected_signals():
    #         p3 = Person.objects.create(
    #             team=self.team,
    #             properties={"prop": 3},
    #             version=3,
    #             is_identified=False,
    #             created_at="2022-03-04T12:00:00Z",
    #         )
    #         p4 = Person.objects.create(
    #             team=self.team,
    #             properties={"prop": 4},
    #             version=4,
    #             is_identified=True,
    #             created_at="2022-04-04T12:00:00Z",
    #         )
    #
    #     self.assertEqual(len(self.get_clickhouse_persons()), 2)
    #
    #     setup_async_migrations(ignore_posthog_version=True)
    #     migration_successful = start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)
    #     self.assertTrue(migration_successful)

    def _create_tile_with_no_filters_hash(self, dashboard, insight):
        # can't use the model to create the tile or the filters_hash is populated
        execute_op_postgres(
            sql=f"""insert into posthog_dashboardtile
                (dashboard_id, insight_id, layouts)
            values ({dashboard.id}, {insight.id}, '{{}}');""",
            query_id="insert the tile",
        )
