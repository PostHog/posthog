import importlib

import pytest

from django.apps import apps as global_apps

from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam, DuckLakeBackfill
from posthog.models import Organization, Team

# The migration module name starts with a digit, so it can't be imported with a plain `import`.
_migration = importlib.import_module("posthog.migrations.1233_backfill_duckgresserverteam")
backfill_duckgres_server_teams = _migration.backfill_duckgres_server_teams


def _server(org: Organization) -> DuckgresServer:
    return DuckgresServer.objects.create(
        organization=org, host="h", port=5432, database="ducklake", username="root", password="x"
    )


@pytest.mark.django_db
class TestBackfillDuckgresServerTeams:
    def test_links_existing_backfill_teams_to_their_org_server(self):
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = _server(org)
        DuckLakeBackfill.objects.create(team=team, table_suffix=None)

        backfill_duckgres_server_teams(global_apps, None)

        link = DuckgresServerTeam.objects.get(team_id=team.id)
        assert link.server_id == server.id
        # Legacy rows keep writing to the shared tables — the backfill never sets a suffix.
        assert DuckLakeBackfill.objects.get(team_id=team.id).table_suffix is None

    def test_skips_teams_whose_org_has_no_server(self):
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        DuckLakeBackfill.objects.create(team=team)

        backfill_duckgres_server_teams(global_apps, None)

        assert not DuckgresServerTeam.objects.filter(team_id=team.id).exists()

    def test_is_idempotent_and_preserves_existing_membership(self):
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = _server(org)
        DuckLakeBackfill.objects.create(team=team)
        DuckgresServerTeam.objects.create(server=server, team=team)

        backfill_duckgres_server_teams(global_apps, None)
        backfill_duckgres_server_teams(global_apps, None)

        assert DuckgresServerTeam.objects.filter(team_id=team.id).count() == 1
