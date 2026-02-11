from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Dashboard, Insight, Project, Team
from posthog.models.cohort import Cohort
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.resource_transfer.resource_transfer import ResourceTransfer


class TestResourceTransferPreview(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dest_project = Project.objects.create(
            id=Team.objects.increment_id_sequence(), organization=self.organization
        )
        self.dest_team = Team.objects.create(
            id=self.dest_project.id, project=self.dest_project, organization=self.organization
        )

    def _preview_url(self) -> str:
        return f"/api/organizations/{self.organization.id}/resource_transfers/preview/"

    def test_preview_returns_mutable_resources_only(self) -> None:
        insight = Insight.objects.create(team=self.team, name="My insight")
        response = self.client.post(
            self._preview_url(),
            {
                "source_team_id": self.team.pk,
                "destination_team_id": self.dest_team.pk,
                "resource_kind": "Insight",
                "resource_id": str(insight.pk),
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        kinds = {r["resource_kind"] for r in data["resources"]}
        assert "Insight" in kinds
        assert "Team" not in kinds
        assert "Project" not in kinds

    def test_preview_includes_display_names_and_friendly_kind(self) -> None:
        insight = Insight.objects.create(team=self.team, name="Revenue chart")
        response = self.client.post(
            self._preview_url(),
            {
                "source_team_id": self.team.pk,
                "destination_team_id": self.dest_team.pk,
                "resource_kind": "Insight",
                "resource_id": str(insight.pk),
            },
        )

        assert response.status_code == status.HTTP_200_OK
        insight_resource = next(r for r in response.json()["resources"] if r["resource_kind"] == "Insight")
        assert insight_resource["display_name"] == "Revenue chart"
        assert insight_resource["friendly_kind"] == "Insight"
        assert insight_resource["user_facing"] is True

    def test_preview_returns_dashboard_with_tiles(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="My dashboard")
        insight = Insight.objects.create(team=self.team, name="My insight")
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        response = self.client.post(
            self._preview_url(),
            {
                "source_team_id": self.team.pk,
                "destination_team_id": self.dest_team.pk,
                "resource_kind": "Dashboard",
                "resource_id": str(dashboard.pk),
            },
        )

        assert response.status_code == status.HTTP_200_OK
        resources = response.json()["resources"]
        kinds = {r["resource_kind"] for r in resources}
        assert "Dashboard" in kinds
        assert "Insight" in kinds
        assert "DashboardTile" in kinds

        user_facing_kinds = {r["resource_kind"] for r in resources if r["user_facing"]}
        assert "Dashboard" in user_facing_kinds
        assert "Insight" in user_facing_kinds
        assert "DashboardTile" not in user_facing_kinds

        tile_resource = next(r for r in resources if r["resource_kind"] == "DashboardTile")
        assert tile_resource["friendly_kind"] == "Dashboard tile"

    def test_preview_includes_suggested_substitution_from_previous_transfer(self) -> None:
        insight = Insight.objects.create(team=self.team, name="My insight")
        dest_insight = Insight.objects.create(team=self.dest_team, name="Copied insight")

        ResourceTransfer.objects.create(
            source_team=self.team,
            destination_team=self.dest_team,
            resource_kind="Insight",
            resource_id=str(insight.pk),
            duplicated_resource_id=str(dest_insight.pk),
        )

        response = self.client.post(
            self._preview_url(),
            {
                "source_team_id": self.team.pk,
                "destination_team_id": self.dest_team.pk,
                "resource_kind": "Insight",
                "resource_id": str(insight.pk),
            },
        )

        assert response.status_code == status.HTTP_200_OK
        insight_resource = next(r for r in response.json()["resources"] if r["resource_kind"] == "Insight")
        assert "suggested_substitution" in insight_resource
        assert insight_resource["suggested_substitution"]["resource_id"] == str(dest_insight.pk)
        assert insight_resource["suggested_substitution"]["display_name"] == "Copied insight"

    def test_preview_no_substitution_without_previous_transfer(self) -> None:
        insight = Insight.objects.create(team=self.team, name="My insight")
        response = self.client.post(
            self._preview_url(),
            {
                "source_team_id": self.team.pk,
                "destination_team_id": self.dest_team.pk,
                "resource_kind": "Insight",
                "resource_id": str(insight.pk),
            },
        )

        assert response.status_code == status.HTTP_200_OK
        insight_resource = next(r for r in response.json()["resources"] if r["resource_kind"] == "Insight")
        assert "suggested_substitution" not in insight_resource

    @parameterized.expand(
        [
            ("same_team", True),
            ("missing_resource", False),
        ]
    )
    def test_preview_validation_errors(self, _name: str, same_team: bool) -> None:
        if same_team:
            response = self.client.post(
                self._preview_url(),
                {
                    "source_team_id": self.team.pk,
                    "destination_team_id": self.team.pk,
                    "resource_kind": "Insight",
                    "resource_id": "999999",
                },
            )
        else:
            response = self.client.post(
                self._preview_url(),
                {
                    "source_team_id": self.team.pk,
                    "destination_team_id": self.dest_team.pk,
                    "resource_kind": "Insight",
                    "resource_id": "999999",
                },
            )

        assert response.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)


class TestResourceTransferTransfer(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dest_project = Project.objects.create(
            id=Team.objects.increment_id_sequence(), organization=self.organization
        )
        self.dest_team = Team.objects.create(
            id=self.dest_project.id, project=self.dest_project, organization=self.organization
        )

    def _transfer_url(self) -> str:
        return f"/api/organizations/{self.organization.id}/resource_transfers/transfer/"

    def test_transfer_creates_resources_in_destination(self) -> None:
        insight = Insight.objects.create(team=self.team, name="My insight")
        response = self.client.post(
            self._transfer_url(),
            {
                "source_team_id": self.team.pk,
                "destination_team_id": self.dest_team.pk,
                "resource_kind": "Insight",
                "resource_id": str(insight.pk),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["count"] >= 1
        assert any(r["kind"] == "Insight" for r in data["created_resources"])

    def test_transfer_with_substitution_uses_existing_resource(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="My dashboard")
        insight = Insight.objects.create(team=self.team, name="My insight")
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        dest_insight = Insight.objects.create(team=self.dest_team, name="Existing insight")

        response = self.client.post(
            self._transfer_url(),
            {
                "source_team_id": self.team.pk,
                "destination_team_id": self.dest_team.pk,
                "resource_kind": "Dashboard",
                "resource_id": str(dashboard.pk),
                "substitutions": [
                    {
                        "source_resource_kind": "Insight",
                        "source_resource_id": str(insight.pk),
                        "destination_resource_kind": "Insight",
                        "destination_resource_id": str(dest_insight.pk),
                    },
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

        new_tiles = DashboardTile.objects.filter(dashboard__team=self.dest_team)
        assert new_tiles.exists()
        tile_insight_ids = set(new_tiles.values_list("insight_id", flat=True))
        assert dest_insight.pk in tile_insight_ids

    def test_transfer_without_substitutions_copies_everything(self) -> None:
        insight = Insight.objects.create(team=self.team, name="My insight")
        initial_insight_count = Insight.objects.filter(team=self.dest_team).count()

        response = self.client.post(
            self._transfer_url(),
            {
                "source_team_id": self.team.pk,
                "destination_team_id": self.dest_team.pk,
                "resource_kind": "Insight",
                "resource_id": str(insight.pk),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert Insight.objects.filter(team=self.dest_team).count() == initial_insight_count + 1

    def test_transfer_creates_resource_transfer_records(self) -> None:
        insight = Insight.objects.create(team=self.team, name="My insight")
        response = self.client.post(
            self._transfer_url(),
            {
                "source_team_id": self.team.pk,
                "destination_team_id": self.dest_team.pk,
                "resource_kind": "Insight",
                "resource_id": str(insight.pk),
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        transfers = ResourceTransfer.objects.filter(
            source_team=self.team,
            destination_team=self.dest_team,
            resource_kind="Insight",
        )
        assert transfers.count() == 1

        transfer = transfers.first()
        assert transfer is not None
        assert transfer.resource_id == str(insight.pk)
        assert transfer.duplicated_resource_id != ""

    def test_transfer_rejects_same_team(self) -> None:
        insight = Insight.objects.create(team=self.team, name="My insight")
        response = self.client.post(
            self._transfer_url(),
            {
                "source_team_id": self.team.pk,
                "destination_team_id": self.team.pk,
                "resource_kind": "Insight",
                "resource_id": str(insight.pk),
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestResourceTransferSearch(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dest_project = Project.objects.create(
            id=Team.objects.increment_id_sequence(), organization=self.organization
        )
        self.dest_team = Team.objects.create(
            id=self.dest_project.id, project=self.dest_project, organization=self.organization
        )

    def _search_url(self) -> str:
        return f"/api/organizations/{self.organization.id}/resource_transfers/search/"

    def test_search_returns_resources_in_target_team(self) -> None:
        Insight.objects.create(team=self.dest_team, name="Target insight A")
        Insight.objects.create(team=self.dest_team, name="Target insight B")
        Insight.objects.create(team=self.team, name="Source insight")

        response = self.client.post(
            self._search_url(),
            {
                "team_id": self.dest_team.pk,
                "resource_kind": "Insight",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        names = {r["display_name"] for r in response.json()["results"]}
        assert "Target insight A" in names
        assert "Target insight B" in names
        assert "Source insight" not in names

    def test_search_filters_by_query(self) -> None:
        Insight.objects.create(team=self.dest_team, name="Revenue chart")
        Insight.objects.create(team=self.dest_team, name="User signups")

        response = self.client.post(
            self._search_url(),
            {
                "team_id": self.dest_team.pk,
                "resource_kind": "Insight",
                "q": "revenue",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["display_name"] == "Revenue chart"

    def test_search_returns_empty_for_no_matches(self) -> None:
        response = self.client.post(
            self._search_url(),
            {
                "team_id": self.dest_team.pk,
                "resource_kind": "Insight",
                "q": "nonexistent",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 0

    @parameterized.expand(
        [
            ("dashboard", "Dashboard"),
            ("cohort", "Cohort"),
        ]
    )
    def test_search_works_for_different_resource_kinds(self, _name: str, kind: str) -> None:
        if kind == "Dashboard":
            Dashboard.objects.create(team=self.dest_team, name="Test dashboard")
        elif kind == "Cohort":
            Cohort.objects.create(team=self.dest_team, name="Test cohort")

        response = self.client.post(
            self._search_url(),
            {
                "team_id": self.dest_team.pk,
                "resource_kind": kind,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) >= 1

    def test_search_with_empty_query_returns_all(self) -> None:
        Insight.objects.create(team=self.dest_team, name="Insight A")
        Insight.objects.create(team=self.dest_team, name="Insight B")

        response = self.client.post(
            self._search_url(),
            {
                "team_id": self.dest_team.pk,
                "resource_kind": "Insight",
                "q": "",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 2

    def test_search_rejects_immutable_kind(self) -> None:
        response = self.client.post(
            self._search_url(),
            {
                "team_id": self.dest_team.pk,
                "resource_kind": "Team",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_search_rejects_unknown_kind(self) -> None:
        response = self.client.post(
            self._search_url(),
            {
                "team_id": self.dest_team.pk,
                "resource_kind": "NonexistentKind",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
