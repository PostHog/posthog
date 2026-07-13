from posthog.test.base import BaseTest

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from products.dashboards.backend.admin.dashboard_admin import DashboardAdmin
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.models.insight import Insight


class TestDashboardAdminRestore(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.admin = DashboardAdmin(Dashboard, AdminSite())
        self.factory = RequestFactory()

    def _post_request(self):
        request = self.factory.post("/")
        request.user = self.user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_restore_selected_restores_tiles_and_co_deleted_insights_but_skips_live_dashboards(self):
        co_deleted_insight = Insight.objects.create(team=self.team, name="co-deleted insight", deleted=True)
        deleted_dashboard = Dashboard.objects.create(team=self.team, name="deleted dashboard", deleted=True)
        deleted_tile = DashboardTile.objects_including_soft_deleted.create(
            dashboard=deleted_dashboard, insight=co_deleted_insight, deleted=True
        )
        # A live dashboard from which a tile was intentionally removed before the action:
        # restore must not resurrect it, or the deleted=True guard has been dropped.
        live_dashboard = Dashboard.objects.create(team=self.team, name="live dashboard")
        removed_insight = Insight.objects.create(team=self.team, name="intentionally removed")
        removed_tile = DashboardTile.objects_including_soft_deleted.create(
            dashboard=live_dashboard, insight=removed_insight, deleted=True
        )

        queryset = Dashboard.objects_including_soft_deleted.filter(id__in=[deleted_dashboard.id, live_dashboard.id])
        self.admin.restore_selected(self._post_request(), queryset)

        deleted_dashboard.refresh_from_db()
        deleted_tile.refresh_from_db()
        co_deleted_insight.refresh_from_db()
        removed_tile.refresh_from_db()
        assert deleted_dashboard.deleted is False
        assert deleted_tile.deleted is False
        assert co_deleted_insight.deleted is False
        assert removed_tile.deleted is True

    def test_bulk_hard_delete_action_is_not_offered(self):
        actions = self.admin.get_actions(self._post_request())
        assert "delete_selected" not in actions
        assert "restore_selected" in actions
