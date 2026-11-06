import pytest

from django.db.models.deletion import ProtectedError

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.team.util import _delete_misc_small_tables_for_teams, delete_team_records

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.backend.models.dashboard_widget import DashboardWidget

# A plain django_db is enough: PROTECT raises while the cascade is being collected, not at COMMIT,
# so the rollback-based TestCase sees it.
pytestmark = [pytest.mark.django_db]


def _team_with_widget_on_a_tile(tile_deleted: bool) -> int:
    _, _, team = Organization.objects.bootstrap(None)
    dashboard = Dashboard.objects.create(team=team, name="dashboard")
    widget = DashboardWidget.objects.for_team(team.id).create(team=team, widget_type="usage")
    DashboardTile.objects.create(dashboard=dashboard, widget=widget, deleted=tile_deleted or None)
    return team.id


def test_team_cascade_is_blocked_by_a_widget_on_a_tile():
    team_id = _team_with_widget_on_a_tile(tile_deleted=False)

    with pytest.raises(ProtectedError):
        delete_team_records([team_id])


@pytest.mark.parametrize("tile_deleted", [False, True])
def test_predelete_unblocks_team_deletion(tile_deleted: bool):
    team_id = _team_with_widget_on_a_tile(tile_deleted=tile_deleted)

    _delete_misc_small_tables_for_teams([team_id])
    delete_team_records([team_id])

    assert not Team.objects.filter(id=team_id).exists()
