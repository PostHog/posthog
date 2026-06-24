from posthog.test.base import BaseTest

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from posthog.admin.admins.ducklake_backfill_admin import DuckLakeBackfillAdmin
from posthog.models import DuckLakeBackfill


class TestDuckLakeBackfillAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.admin = DuckLakeBackfillAdmin(DuckLakeBackfill, AdminSite())
        self.request = RequestFactory().get("/")
        self.request.user = self.user

    def test_table_suffix_is_readonly(self) -> None:
        # `table_suffix` is write-once — editing it in admin would move a team's warehouse
        # schema/tables and orphan the old ones. It must never be editable here.
        backfill = DuckLakeBackfill.objects.create(team=self.team, enabled=True, table_suffix="acme")
        assert "table_suffix" in self.admin.get_readonly_fields(self.request, backfill)
