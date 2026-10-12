import pytest
from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.facade.dashboard_creation import (
    DashboardCreationDenied,
    NewDashboard,
    NewInsightTile,
    NewTextTile,
    TileLayout,
    create_dashboard_with_tiles,
)
from products.dashboards.backend.models.dashboard import Dashboard


def _dashboard(key: str = "import-1") -> NewDashboard:
    return NewDashboard(
        name="Imported",
        description="",
        idempotency_key=key,
        tiles=(
            NewTextTile(body="## Traffic", layout=TileLayout(x=0, y=0, w=12, h=1)),
            NewInsightTile(
                name="Requests",
                description="",
                query={"kind": "MetricsQuery", "language": "promql", "promql": "up", "clauses": []},
                layout=TileLayout(x=0, y=1, w=6, h=3),
            ),
        ),
    )


@pytest.mark.ee
class TestCreateDashboardWithTiles(APIBaseTest):
    @parameterized.expand([("dashboard",), ("insight",)])
    def test_needs_editor_access_to_dashboards_and_insights(self, resource: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=None,
            access_level="viewer",
            organization_member=self.organization_membership,
        )

        with pytest.raises(DashboardCreationDenied):
            create_dashboard_with_tiles(team_id=self.team.id, user_id=self.user.id, dashboard=_dashboard())

        assert not Dashboard.objects.filter(team=self.team).exists()

    def test_a_repeated_idempotency_key_creates_no_second_dashboard(self) -> None:
        created = create_dashboard_with_tiles(team_id=self.team.id, user_id=self.user.id, dashboard=_dashboard())

        with pytest.raises(ValueError):
            create_dashboard_with_tiles(team_id=self.team.id, user_id=self.user.id, dashboard=_dashboard())

        assert (created.insight_count, created.text_tile_count) == (1, 1)
        assert list(Dashboard.objects.filter(team=self.team).values_list("id", flat=True)) == [created.id]
