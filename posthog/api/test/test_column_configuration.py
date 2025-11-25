from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import ColumnConfiguration


class TestColumnConfigurationAPI(APIBaseTest):
    def test_create_column_configuration(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {"context_key": "survey:123", "columns": ["*", "person", "timestamp"]},
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["context_key"] == "survey:123"
        assert response.json()["columns"] == ["*", "person", "timestamp"]

    def test_create_duplicate_returns_409(self):
        self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {"context_key": "survey:123", "columns": ["*", "person"]},
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {"context_key": "survey:123", "columns": ["*", "timestamp"]},
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "already exists" in response.json()["error"]
        config = ColumnConfiguration.objects.get(team=self.team, context_key="survey:123")
        assert config.columns == ["*", "person"]

    def test_update_via_patch(self):
        create_response = self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {"context_key": "survey:123", "columns": ["*", "person"]},
        )
        config_id = create_response.json()["id"]

        response = self.client.patch(
            f"/api/environments/{self.team.id}/column_configurations/{config_id}/",
            {"columns": ["*", "timestamp"]},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["columns"] == ["*", "timestamp"]
        assert ColumnConfiguration.objects.filter(team=self.team, context_key="survey:123").count() == 1

    def test_get_by_context_key(self):
        self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {"context_key": "survey:123", "columns": ["*", "person"]},
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/column_configurations/", {"context_key": "survey:123"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["context_key"] == "survey:123"

    def test_missing_context_key(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {"columns": ["*", "person"]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "context_key is required" in response.json()["error"]

    def test_missing_columns(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {"context_key": "survey:123"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "columns is required" in response.json()["error"]

    def test_empty_columns_list(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {"context_key": "survey:123", "columns": []},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "columns cannot be empty" in response.json()["error"]

    def test_non_string_columns(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {"context_key": "survey:123", "columns": ["*", 123, "person"]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "all columns must be strings" in response.json()["error"]

    def test_too_many_columns(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {"context_key": "survey:123", "columns": [f"col_{i}" for i in range(101)]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "cannot configure more than 100 columns" in response.json()["error"]

    def test_team_isolation(self):
        other_team = self.organization.teams.create(name="Other Team")

        self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {"context_key": "survey:123", "columns": ["*", "person"]},
        )

        response = self.client.get(f"/api/environments/{other_team.id}/column_configurations/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 0
