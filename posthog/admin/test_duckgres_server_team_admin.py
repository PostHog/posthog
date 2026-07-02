from posthog.test.base import BaseTest

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from posthog.admin.admins.duckgres_server_team_admin import DuckgresServerTeamAdmin
from posthog.models import DuckgresServer, DuckgresServerTeam


class TestDuckgresServerTeamAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.admin = DuckgresServerTeamAdmin(DuckgresServerTeam, AdminSite())
        self.request = RequestFactory().get("/")
        self.request.user = self.user

    def test_table_suffix_is_readonly(self) -> None:
        # `table_suffix` is write-once — editing it in admin would move a team's warehouse
        # schema/tables and orphan the old ones. It must never be editable here.
        server = DuckgresServer.objects.create(
            organization=self.organization, host="h", port=5432, database="ducklake", username="root", password="x"
        )
        link = DuckgresServerTeam.objects.create(
            server=server, team=self.team, backfill_enabled=True, table_suffix="acme"
        )
        assert "table_suffix" in self.admin.get_readonly_fields(self.request, link)
