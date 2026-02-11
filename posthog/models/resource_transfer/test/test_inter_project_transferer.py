from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Dashboard, Insight, Project, Team
from posthog.models.dashboard_tile import DashboardTile, Text
from posthog.models.resource_transfer.inter_project_transferer import (
    build_resource_duplication_graph,
    dag_sort_duplication_graph,
    duplicate_resource_to_new_team,
)
from posthog.models.resource_transfer.resource_transfer import ResourceTransfer


class TestBuildResourceDuplicationGraph(BaseTest):
    def _create_destination_team(self) -> Team:
        project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=self.organization)
        return Team.objects.create(id=project.id, project=project, organization=self.organization)

    def test_standalone_insight_graph_has_insight_and_team(self) -> None:
        insight = Insight.objects.create(team=self.team, name="My insight")
        graph = list(build_resource_duplication_graph(insight, set()))

        model_types = {v.model for v in graph}
        assert Insight in model_types
        assert Team in model_types

    def test_standalone_dashboard_graph_has_dashboard_and_team(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="My dashboard")
        graph = list(build_resource_duplication_graph(dashboard, set()))

        model_types = {v.model for v in graph}
        assert Dashboard in model_types
        assert Team in model_types

    def test_dashboard_with_insight_tile_includes_all_related_resources(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="My dashboard")
        insight = Insight.objects.create(team=self.team, name="My insight")
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        graph = list(build_resource_duplication_graph(dashboard, set()))
        model_types = {v.model for v in graph}

        assert Dashboard in model_types
        assert Insight in model_types
        assert DashboardTile in model_types
        assert Team in model_types

    def test_dashboard_text_tiles_reachable_via_m2m(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="My dashboard")
        text = Text.objects.create(team=self.team, body="Hello world")
        DashboardTile.objects.create(dashboard=dashboard, text=text)

        graph = list(build_resource_duplication_graph(dashboard, set()))
        model_types = {v.model for v in graph}

        assert Dashboard in model_types
        assert Text in model_types
        assert DashboardTile in model_types

    def test_immutable_resources_have_no_edges(self) -> None:
        insight = Insight.objects.create(team=self.team, name="My insight")
        graph = list(build_resource_duplication_graph(insight, set()))

        team_vertex = next(v for v in graph if v.model is Team)
        assert team_vertex.edges == []

    def test_exclude_set_prevents_revisiting_resources(self) -> None:
        insight = Insight.objects.create(team=self.team, name="My insight")
        exclude: set[tuple[str, Any]] = {("Insight", insight.pk)}

        graph = list(build_resource_duplication_graph(insight, exclude))
        assert len(graph) == 0

    def test_raises_for_unvisitable_model(self) -> None:
        from posthog.models import Annotation

        annotation = Annotation.objects.create(team=self.team, content="My annotation")
        with self.assertRaises(TypeError):
            list(build_resource_duplication_graph(annotation, set()))


class TestDagSortDuplicationGraph(BaseTest):
    def test_dag_sorts_vertices_so_dependencies_come_first(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="My dashboard")
        insight = Insight.objects.create(team=self.team, name="My insight")
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        graph = list(build_resource_duplication_graph(dashboard, set()))
        dag = dag_sort_duplication_graph(graph)
        model_order = [v.model for v in dag]

        assert model_order.index(Team) < model_order.index(Dashboard)
        assert model_order.index(Team) < model_order.index(Insight)
        assert model_order.index(Dashboard) < model_order.index(DashboardTile)
        assert model_order.index(Insight) < model_order.index(DashboardTile)


class TestDuplicateResourceToNewTeam(BaseTest):
    def _create_destination_team(self) -> Team:
        project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=self.organization)
        return Team.objects.create(id=project.id, project=project, organization=self.organization)

    def test_duplicates_standalone_insight(self) -> None:
        dest_team = self._create_destination_team()
        insight = Insight.objects.create(team=self.team, name="My insight", filters={"events": [{"id": "$pageview"}]})

        results = duplicate_resource_to_new_team(insight, dest_team)
        new_insights = [r for r in results if isinstance(r, Insight)]

        assert len(new_insights) == 1
        assert new_insights[0].pk != insight.pk
        assert new_insights[0].team == dest_team
        assert new_insights[0].name == "My insight"
        assert new_insights[0].filters == {"events": [{"id": "$pageview"}]}

    def test_duplicates_standalone_dashboard(self) -> None:
        dest_team = self._create_destination_team()
        dashboard = Dashboard.objects.create(team=self.team, name="My dashboard")

        results = duplicate_resource_to_new_team(dashboard, dest_team)
        new_dashboards = [r for r in results if isinstance(r, Dashboard)]

        assert len(new_dashboards) == 1
        assert new_dashboards[0].pk != dashboard.pk
        assert new_dashboards[0].team == dest_team
        assert new_dashboards[0].name == "My dashboard"

    def test_duplicates_dashboard_with_insight_tile(self) -> None:
        dest_team = self._create_destination_team()
        dashboard = Dashboard.objects.create(team=self.team, name="My dashboard")
        insight = Insight.objects.create(team=self.team, name="My insight")
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        results = duplicate_resource_to_new_team(dashboard, dest_team)

        new_dashboards = [r for r in results if isinstance(r, Dashboard)]
        new_insights = [r for r in results if isinstance(r, Insight)]
        new_tiles = [r for r in results if isinstance(r, DashboardTile)]

        assert len(new_dashboards) == 1
        assert len(new_insights) == 1
        assert len(new_tiles) == 1

        assert new_tiles[0].dashboard == new_dashboards[0]
        assert new_tiles[0].insight == new_insights[0]
        assert new_insights[0].team == dest_team

    def test_duplicates_dashboard_with_multiple_insight_tiles(self) -> None:
        dest_team = self._create_destination_team()
        dashboard = Dashboard.objects.create(team=self.team, name="My dashboard")
        insight_a = Insight.objects.create(team=self.team, name="Insight A")
        insight_b = Insight.objects.create(team=self.team, name="Insight B")
        DashboardTile.objects.create(dashboard=dashboard, insight=insight_a)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight_b)

        results = duplicate_resource_to_new_team(dashboard, dest_team)

        new_insights = [r for r in results if isinstance(r, Insight)]
        new_tiles = [r for r in results if isinstance(r, DashboardTile)]

        assert len(new_insights) == 2
        assert len(new_tiles) == 2

        for r in new_insights:
            assert r.team == dest_team

    def test_does_not_modify_source_resources(self) -> None:
        dest_team = self._create_destination_team()
        insight = Insight.objects.create(team=self.team, name="My insight")

        duplicate_resource_to_new_team(insight, dest_team)

        insight.refresh_from_db()
        assert insight.team == self.team
        assert insight.name == "My insight"

    def test_new_insight_gets_fresh_short_id(self) -> None:
        dest_team = self._create_destination_team()
        insight = Insight.objects.create(team=self.team, name="My insight", short_id="abc123")

        results = duplicate_resource_to_new_team(insight, dest_team)
        new_insight = next(r for r in results if isinstance(r, Insight))

        assert new_insight.short_id != "abc123"
        assert new_insight.short_id != ""

    def test_transaction_rolls_back_on_failure(self) -> None:
        dest_team = self._create_destination_team()
        dashboard = Dashboard.objects.create(team=self.team, name="My dashboard")
        initial_count = Dashboard.objects.count()

        from unittest.mock import patch

        with patch(
            "posthog.models.resource_transfer.resource_transfer.ResourceTransfer.objects.bulk_create",
            side_effect=Exception("boom"),
        ):
            with self.assertRaises(Exception):
                duplicate_resource_to_new_team(dashboard, dest_team)

        assert Dashboard.objects.count() == initial_count


class TestResourceTransferRecordCreation(BaseTest):
    def _create_destination_team(self) -> Team:
        project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=self.organization)
        return Team.objects.create(id=project.id, project=project, organization=self.organization)

    def test_creates_transfer_records_for_mutable_resources(self) -> None:
        dest_team = self._create_destination_team()
        dashboard = Dashboard.objects.create(team=self.team, name="My dashboard")
        insight = Insight.objects.create(team=self.team, name="My insight")
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        duplicate_resource_to_new_team(dashboard, dest_team)

        transfers = ResourceTransfer.objects.filter(
            source_team=self.team,
            destination_team=dest_team,
        )
        assert transfers.count() > 0
        kinds = set(transfers.values_list("resource_kind", flat=True))
        assert "Dashboard" in kinds
        assert "Insight" in kinds
        assert "DashboardTile" in kinds

    def test_does_not_create_transfer_records_for_immutable_resources(self) -> None:
        dest_team = self._create_destination_team()
        insight = Insight.objects.create(team=self.team, name="My insight")

        duplicate_resource_to_new_team(insight, dest_team)

        transfers = ResourceTransfer.objects.filter(source_team=self.team, destination_team=dest_team)
        kinds = set(transfers.values_list("resource_kind", flat=True))
        assert "Team" not in kinds
        assert "Project" not in kinds

    @parameterized.expand(
        [
            ("insight", lambda self_: Insight.objects.create(team=self_.team, name="Test")),
            ("dashboard", lambda self_: Dashboard.objects.create(team=self_.team, name="Test")),
        ]
    )
    def test_transfer_record_points_to_newly_created_resource(self, _name: str, create_resource) -> None:
        dest_team = self._create_destination_team()
        resource = create_resource(self)

        results = duplicate_resource_to_new_team(resource, dest_team)
        new_resource = next(r for r in results if type(r) is type(resource) and r.pk != resource.pk)

        transfer = ResourceTransfer.objects.get(
            source_team=self.team,
            destination_team=dest_team,
            resource_kind=type(resource).__name__,
        )
        assert transfer.resource_id == str(resource.pk)
        assert transfer.duplicated_resource_id == str(new_resource.pk)
