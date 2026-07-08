from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.team import Team

from products.data_catalog.backend.facade.enums import MetricStatus
from products.data_catalog.backend.models import Metric


class TestMetricAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/data_catalog/metrics/"

    def test_create_lands_proposed(self) -> None:
        response = self.client.post(self.url, {"name": "mrr", "description": "Monthly revenue"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["name"] == "mrr"
        assert body["status"] == MetricStatus.PROPOSED

    def test_status_and_approval_are_not_writable(self) -> None:
        response = self.client.post(
            self.url,
            {"name": "mrr", "description": "d", "status": "approved", "approved_at": "2020-01-01T00:00:00Z"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["status"] == MetricStatus.PROPOSED
        assert response.json()["approved_at"] is None

    def test_create_is_upsert_on_name(self) -> None:
        self.client.post(self.url, {"name": "mrr", "description": "v1"}, format="json")
        response = self.client.post(self.url, {"name": "mrr", "description": "v2"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert Metric.objects.for_team(self.team.id).count() == 1
        assert self.client.get(f"{self.url}mrr/").json()["description"] == "v2"

    def test_name_addressed_detail_routes(self) -> None:
        self.client.post(self.url, {"name": "mrr", "description": "v1"}, format="json")

        assert self.client.get(f"{self.url}mrr/").status_code == status.HTTP_200_OK

        patched = self.client.patch(f"{self.url}mrr/", {"display_name": "MRR"}, format="json")
        assert patched.status_code == status.HTTP_200_OK
        assert patched.json()["display_name"] == "MRR"

        assert self.client.delete(f"{self.url}mrr/").status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(f"{self.url}mrr/").status_code == status.HTTP_404_NOT_FOUND

    def test_patch_cannot_change_name(self) -> None:
        self.client.post(self.url, {"name": "mrr", "description": "v1"}, format="json")
        response = self.client.patch(f"{self.url}mrr/", {"name": "arr"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_definition_rejected(self) -> None:
        response = self.client.post(
            self.url,
            {"name": "mrr", "description": "d", "definition": {"kind": "RetentionQuery"}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_markdown_definition_accepted(self) -> None:
        response = self.client.post(
            self.url,
            {
                "name": "activation",
                "description": "Activated users",
                "definition": {"kind": "MarkdownDefinition", "markdown": "1. User did A then B within 7 days."},
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["definition_kind"] == "MarkdownDefinition"

    def test_list_is_team_scoped(self) -> None:
        other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        self.client.post(self.url, {"name": "mine", "description": "d"}, format="json")
        Metric.objects.for_team(other_team.id).create(team=other_team, name="theirs", description="d")

        names = [row["name"] for row in self.client.get(self.url).json()["results"]]
        assert names == ["mine"]
