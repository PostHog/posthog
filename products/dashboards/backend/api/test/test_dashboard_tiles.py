import uuid

from posthog.test.base import APIBaseTest

from django.db import connection

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.models.insight import Insight


class TestDashboardTileHardDelete(APIBaseTest):
    def test_hard_delete_removes_orphaned_insight_caching_state(self) -> None:
        # The InsightCachingState model was removed from Django state but its
        # posthog_insightcachingstate table and FK constraint survive the rolling deploy.
        # Django no longer cascades those rows, so without explicit cleanup the FK constraint
        # rejects the hard delete with an IntegrityError.
        dashboard = Dashboard.objects.create(team=self.team, name="d")
        insight = Insight.objects.create(team=self.team, name="i")
        tile = DashboardTile.objects.create(dashboard=dashboard, insight=insight, layouts={})
        tile_id = tile.id
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO posthog_insightcachingstate
                    (id, team_id, insight_id, dashboard_tile_id, cache_key, refresh_attempt, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 0, now(), now())
                """,
                [str(uuid.uuid4()), self.team.id, insight.id, tile_id, "some_cache_key"],
            )

        tile.delete()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM posthog_insightcachingstate WHERE dashboard_tile_id = %s",
                [tile_id],
            )
            assert cursor.fetchone()[0] == 0
        assert not DashboardTile.objects_including_soft_deleted.filter(id=tile_id).exists()
