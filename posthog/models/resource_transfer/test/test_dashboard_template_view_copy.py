from posthog.test.base import BaseTest

from posthog.models import Project, Team
from posthog.models.resource_transfer.dashboard_template_views import copy_warehouse_views_by_name

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery


class TestCopyWarehouseViewsByName(BaseTest):
    def _target_team(self) -> Team:
        project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=self.organization)
        return Team.objects.create(id=project.id, project=project, organization=self.organization)

    def _view(self, team: Team, name: str, sql: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(team=team, name=name, query={"query": sql})

    def test_copies_referenced_view_without_renaming_when_name_is_free(self) -> None:
        target = self._target_team()
        self._view(self.team, "revenue", "SELECT amount FROM stripe_charges")

        remap = copy_warehouse_views_by_name(
            view_names={"revenue"}, source_team=self.team, target_team=target, created_by=self.user
        )

        assert remap == {}  # name was free, so no rewrite needed
        assert DataWarehouseSavedQuery.objects.filter(team=target, name="revenue").exists()

    def test_remaps_name_on_target_collision(self) -> None:
        target = self._target_team()
        self._view(target, "revenue", "SELECT 1")  # occupies the name in the target
        self._view(self.team, "revenue", "SELECT amount FROM stripe_charges")

        remap = copy_warehouse_views_by_name(
            view_names={"revenue"}, source_team=self.team, target_team=target, created_by=self.user
        )

        assert remap == {"revenue": "revenue_copy"}
        assert DataWarehouseSavedQuery.objects.filter(team=target, name="revenue_copy").exists()

    def test_names_without_a_view_are_skipped(self) -> None:
        target = self._target_team()

        remap = copy_warehouse_views_by_name(
            view_names={"a_physical_table"}, source_team=self.team, target_team=target, created_by=self.user
        )

        assert remap == {}
        assert not DataWarehouseSavedQuery.objects.filter(team=target).exists()
