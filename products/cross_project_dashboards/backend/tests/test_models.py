from posthog.test.base import BaseTest

from posthog.models import Team

from products.cross_project_dashboards.backend.models import CrossProjectDashboard, CrossProjectDashboardTile


class TestCrossProjectDashboardModels(BaseTest):
    def _dashboard(self) -> CrossProjectDashboard:
        return CrossProjectDashboard.objects.create(
            organization=self.organization, name="Company overview", created_by=self.user
        )

    def test_tile_references_a_project_and_insight_by_id(self):
        tile = CrossProjectDashboardTile.objects.create(
            dashboard=self._dashboard(),
            organization=self.organization,
            project_id=self.team.pk,
            insight_id=1234,
        )
        assert tile.organization_id == self.organization.id
        assert tile.project_id == self.team.pk
        assert tile.insight_id == 1234

    def test_tile_survives_an_insight_that_does_not_exist(self):
        tile = CrossProjectDashboardTile.objects.create(
            dashboard=self._dashboard(), organization=self.organization, project_id=self.team.pk, insight_id=999999
        )
        assert CrossProjectDashboardTile.objects.filter(pk=tile.pk).exists()

    def test_tile_survives_a_project_that_was_deleted(self):
        # No FK to the project, so deleting one leaves the dashboard loadable and the tile able
        # to report that its source is gone, rather than cascading the tile away with no trace.
        doomed = Team.objects.create(organization=self.organization, name="Doomed project")
        dashboard = self._dashboard()
        tile = CrossProjectDashboardTile.objects.create(
            dashboard=dashboard, organization=self.organization, project_id=doomed.pk, insight_id=42
        )
        doomed_pk = doomed.pk
        doomed.delete()

        tile.refresh_from_db()
        assert tile.project_id == doomed_pk
        assert CrossProjectDashboard.objects.filter(pk=dashboard.pk).exists()

    def test_tile_has_no_team_field(self):
        # A non-FK team_id column makes check-idor-model-coverage.py classify this model as
        # team-scoped, which would demand a manager that scopes reads to a single team.
        field_names = {field.name for field in CrossProjectDashboardTile._meta.get_fields()}
        assert "team" not in field_names
        assert "team_id" not in field_names
