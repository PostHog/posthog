from posthog.test.base import BaseTest

from posthog.models import Project, Team
from posthog.models.resource_transfer.inter_project_transferer import (
    build_resource_duplication_graph,
    duplicate_resource_to_new_team,
)

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery


class TestDataWarehouseSavedQueryTransfer(BaseTest):
    def _create_destination_team(self) -> Team:
        project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=self.organization)
        return Team.objects.create(id=project.id, project=project, organization=self.organization)

    def _saved_query(self, team: Team, name: str, sql: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(team=team, name=name, query={"query": sql})

    def test_graph_includes_saved_query_and_team(self) -> None:
        view = self._saved_query(self.team, "events_view", "SELECT event FROM events")
        model_types = {v.model for v in build_resource_duplication_graph(view, set())}

        assert DataWarehouseSavedQuery in model_types
        assert Team in model_types

    def test_duplicates_standalone_view_unmaterialized(self) -> None:
        dest_team = self._create_destination_team()
        view = self._saved_query(self.team, "events_view", "SELECT event FROM events")
        view.is_materialized = True
        view.status = DataWarehouseSavedQuery.Status.COMPLETED
        view.save()

        results = duplicate_resource_to_new_team(view, dest_team, created_by=self.user)
        copies = [r for r in results if isinstance(r, DataWarehouseSavedQuery)]

        assert len(copies) == 1
        copy = copies[0]
        assert copy.pk != view.pk
        assert copy.team == dest_team
        assert copy.name == "events_view"
        assert copy.query == {"query": "SELECT event FROM events"}
        # Lands fresh: no materialized table, no run status.
        assert copy.is_materialized is False
        assert copy.status is None
        assert copy.table_id is None
        assert copy.sync_frequency_interval is None

    def test_name_collision_gets_identifier_safe_suffix(self) -> None:
        dest_team = self._create_destination_team()
        self._saved_query(dest_team, "events_view", "SELECT 1")
        view = self._saved_query(self.team, "events_view", "SELECT event FROM events")

        results = duplicate_resource_to_new_team(view, dest_team, created_by=self.user)
        copy = next(r for r in results if isinstance(r, DataWarehouseSavedQuery) and r.team == dest_team)

        assert copy.name == "events_view_copy"
        # Must remain a valid SQL identifier (no spaces / parentheses).
        assert " " not in copy.name and "(" not in copy.name

    def test_copies_upstream_view_dependency(self) -> None:
        dest_team = self._create_destination_team()
        self._saved_query(self.team, "base_view", "SELECT event, timestamp FROM events")
        child = self._saved_query(self.team, "child_view", "SELECT event FROM base_view")

        results = duplicate_resource_to_new_team(child, dest_team, created_by=self.user)
        copied_names = {r.name for r in results if isinstance(r, DataWarehouseSavedQuery) and r.team == dest_team}

        assert "child_view" in copied_names
        assert "base_view" in copied_names
