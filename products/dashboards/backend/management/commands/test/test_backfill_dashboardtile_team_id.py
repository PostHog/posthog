from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.db import connection

from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile, Text


def _null_out_team_ids(tile_ids: list[int]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE posthog_dashboardtile SET team_id = NULL WHERE id = ANY(%s)",
            [tile_ids],
        )


def _team_id_for(tile_id: int) -> int | None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT team_id FROM posthog_dashboardtile WHERE id = %s", [tile_id])
        row = cursor.fetchone()
        assert row is not None
        return row[0]


class TestBackfillDashboardTileTeamId(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.stdout = StringIO()

        self.other_organization = Organization.objects.create(name="other org")
        self.other_team = Team.objects.create(organization=self.other_organization, name="other team")

        self.dashboard_a = Dashboard.objects.create(team=self.team, name="A")
        self.dashboard_b = Dashboard.objects.create(team=self.other_team, name="B")

        text_a = Text.objects.create(team=self.team, body="hi A")
        text_b = Text.objects.create(team=self.other_team, body="hi B")
        self.tile_a = DashboardTile.objects.create(dashboard=self.dashboard_a, text=text_a)
        self.tile_b = DashboardTile.objects.create(dashboard=self.dashboard_b, text=text_b)

    def test_backfills_team_id_from_dashboard(self) -> None:
        _null_out_team_ids([self.tile_a.id, self.tile_b.id])
        self.assertIsNone(_team_id_for(self.tile_a.id))
        self.assertIsNone(_team_id_for(self.tile_b.id))

        call_command("backfill_dashboardtile_team_id", stdout=self.stdout)

        self.assertEqual(_team_id_for(self.tile_a.id), self.team.id)
        self.assertEqual(_team_id_for(self.tile_b.id), self.other_team.id)

    def test_second_run_is_a_noop(self) -> None:
        _null_out_team_ids([self.tile_a.id, self.tile_b.id])

        call_command("backfill_dashboardtile_team_id", stdout=self.stdout)

        second_stdout = StringIO()
        call_command("backfill_dashboardtile_team_id", stdout=second_stdout)
        self.assertIn("Updated 0 tile(s) in 0 batch(es)", second_stdout.getvalue())

    def test_skips_tiles_that_already_have_team_id(self) -> None:
        _null_out_team_ids([self.tile_a.id])

        call_command("backfill_dashboardtile_team_id", stdout=self.stdout)

        self.tile_b.refresh_from_db(fields=["team_id"])
        self.assertEqual(self.tile_b.team_id, self.other_team.id)
        self.assertEqual(_team_id_for(self.tile_a.id), self.team.id)
