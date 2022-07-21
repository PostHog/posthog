import pytest

from posthog.async_migrations.runner import start_async_migration
from posthog.async_migrations.setup import get_async_migration_definition, setup_async_migrations
from posthog.async_migrations.test.util import AsyncMigrationBaseTest
from posthog.async_migrations.utils import execute_op_postgres
from posthog.models import Dashboard, DashboardTile, Insight
from posthog.models.utils import UUIDT

MIGRATION_NAME = "0006_generate_dashboard_tile_filters_hashes"


@pytest.mark.async_migrations
class Test0006GenerateDashboardTilesFiltersHashes(AsyncMigrationBaseTest):
    def test_is_not_required_with_no_hashless_tiles(self):
        migration = get_async_migration_definition(MIGRATION_NAME)

        dashboard = Dashboard.objects.create(team=self.team, name="a dashboard")
        insight = Insight.objects.create(team=self.team, name="an insight", filters={"events": [{"id": "$pageview"}],})
        DashboardTile.objects.create(insight=insight, dashboard=dashboard)
        self.assertEqual(0, DashboardTile.objects.filter(filters_hash=None).count())

        self.assertFalse(migration.is_required())

    def test_is_required_when_hashless_tiles(self):
        migration = get_async_migration_definition(MIGRATION_NAME)

        dashboard = Dashboard.objects.create(team=self.team, name="a dashboard")
        insight = Insight.objects.create(team=self.team, name="an insight", filters={"events": [{"id": "$pageview"}],})
        self._create_tile_with_no_filters_hash(dashboard, insight)
        self.assertEqual(1, DashboardTile.objects.filter(filters_hash=None).count())
        self.assertTrue(migration.is_required())

    def test_filters_hashes_are_populated(self):
        for i in range(4):  # force the processing to page
            dashboard = Dashboard.objects.create(team=self.team, name=i)
            insight = Insight.objects.create(team=self.team, name=i, filters={"events": [{"id": "$pageview"}],})
            self._create_tile_with_no_filters_hash(dashboard, insight)

        setup_async_migrations(ignore_posthog_version=True)
        migration_successful = start_async_migration(MIGRATION_NAME, ignore_posthog_version=True)

        self.assertTrue(migration_successful)
        self.assertEqual(0, DashboardTile.objects.filter(filters_hash=None).count())

    def _create_tile_with_no_filters_hash(self, dashboard, insight):
        # can't use the model to create the tile or the filters_hash is populated
        execute_op_postgres(
            sql=f"""
            INSERT INTO posthog_dashboardtile (dashboard_id, insight_id, layouts)
            VALUES ({dashboard.id}, {insight.id}, '{{}}');
            """,
            query_id=str(UUIDT()),
        )
