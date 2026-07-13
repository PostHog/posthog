from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpRequest
from django.test import RequestFactory

from products.dashboards.backend.admin.dashboard_admin import DashboardAdmin
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.models.insight import Insight


def _attach_messages(request) -> None:
    # The request param is deliberately untyped: session and _messages are set by
    # middleware at runtime, so assigning them on a typed request fails type checking.
    request.session = {}
    request._messages = FallbackStorage(request)


class TestDashboardAdminRestore(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.admin = DashboardAdmin(Dashboard, AdminSite())
        self.factory = RequestFactory()

    def _post_request(self) -> HttpRequest:
        request = self.factory.post("/")
        request.user = self.user
        _attach_messages(request)
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

    def test_restore_reports_no_negative_skip_when_queryset_is_filtered_to_deleted(self):
        # The admin changelist passes an action queryset already filtered to deleted=True
        # (the "deleted: Yes" sidebar filter). Counting after the restore would then drop the
        # just-restored rows and report a negative "Skipped" count.
        deleted_dashboard = Dashboard.objects.create(team=self.team, name="deleted dashboard", deleted=True)
        queryset = Dashboard.objects_including_soft_deleted.filter(id=deleted_dashboard.id, deleted=True)

        with patch.object(self.admin, "message_user") as message_user:
            self.admin.restore_selected(self._post_request(), queryset)

        assert message_user.call_args[0][1] == "Restored 1 dashboards."

    def test_bulk_hard_delete_action_is_not_offered(self):
        actions = self.admin.get_actions(self._post_request())
        assert "delete_selected" not in actions
        assert "restore_selected" in actions
