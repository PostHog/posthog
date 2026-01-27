from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import ColumnConfiguration, User


class TestColumnConfigurationAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.another_user = User.objects.create_and_join(self.organization, email="foo@bar.com", password="top-secret")

    def test_create_column_configuration(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {"context_key": "survey:123", "columns": ["*", "person", "timestamp"]},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["context_key"] == "survey:123"
        assert data["columns"] == ["*", "person", "timestamp"]
        assert data["name"] == "Column configuration", "Should have default name"
        assert data["visibility"] == ColumnConfiguration.Visibility.SHARED, "Should have default visibility"

    def test_unique_user_view_name_constraint(self):
        config = ColumnConfiguration.objects.create(
            team=self.team,
            visibility=ColumnConfiguration.Visibility.PRIVATE,
            name="Dupe",
            context_key="dupe-key",
            columns=["*", "person", "timestamp"],
            created_by=self.another_user,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {
                "name": "Dupe",
                "context_key": "dupe-key",
                "columns": ["*", "person"],
                "visibility": ColumnConfiguration.Visibility.PRIVATE,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, (
            "Different users may have views with the same name and context key"
        )
        data = response.json()
        assert data["context_key"] == "dupe-key"
        assert data["columns"] == ["*", "person"], "New config should have columns passed in the request"
        config.refresh_from_db()
        assert config.columns == ["*", "person", "timestamp"], "Old config should not change columns"

        response = self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {
                "name": "Dupe",
                "context_key": "dupe-key",
                "columns": ["*"],
                "visibility": ColumnConfiguration.Visibility.PRIVATE,
            },
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["detail"] == "A private view with this name already exists"

    def test_unique_team_view_name_constraint(self):
        ColumnConfiguration.objects.create(
            team=self.team,
            visibility=ColumnConfiguration.Visibility.SHARED,
            name="Dupe",
            context_key="dupe-key",
            columns=["*", "person", "timestamp"],
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/column_configurations/",
            {
                "name": "Dupe",
                "context_key": "dupe-key",
                "columns": ["*", "person"],
                "visibility": ColumnConfiguration.Visibility.SHARED,
            },
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["detail"] == "A shared view with this name already exists"

    def test_user_can_only_access_their_private_views(self):
        ColumnConfiguration.objects.create(
            team=self.team,
            visibility=ColumnConfiguration.Visibility.PRIVATE,
            context_key="context-key",
            columns=["*", "person", "timestamp"],
            created_by=self.another_user,
        )
        config = ColumnConfiguration.objects.create(
            team=self.team,
            visibility=ColumnConfiguration.Visibility.PRIVATE,
            context_key="context-key",
            columns=["*", "person", "timestamp"],
            created_by=self.user,
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/column_configurations/", {"context_key": "context-key"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["id"] == str(config.id)

    def test_user_can_only_edit_their_views(self):
        another_config = ColumnConfiguration.objects.create(
            team=self.team,
            visibility=ColumnConfiguration.Visibility.PRIVATE,
            context_key="context-key",
            columns=["*", "person", "timestamp"],
            created_by=self.another_user,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/column_configurations/{str(another_config.id)}", {"name": "New name"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "You do not have permission to change this view"

    def test_user_can_only_delete_their_views(self):
        another_config = ColumnConfiguration.objects.create(
            team=self.team,
            visibility=ColumnConfiguration.Visibility.PRIVATE,
            context_key="context-key",
            columns=["*", "person", "timestamp"],
            created_by=self.another_user,
        )

        response = self.client.delete(
            f"/api/environments/{self.team.id}/column_configurations/{str(another_config.id)}"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "You do not have permission to change this view"

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
        context_keys = ["survey:123", "people-list"]
        for context in context_keys:
            ColumnConfiguration.objects.create(team=self.team, context_key=context, columns=["*", "person"])

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
