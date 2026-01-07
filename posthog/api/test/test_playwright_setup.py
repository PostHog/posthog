from posthog.test.base import APIBaseTest

from django.test import override_settings

from rest_framework import status

from posthog.models import Organization, PersonalAPIKey, Team, User


class TestPlaywrightSetup(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False  # Each test gets fresh data to prevent isolation issues

    def test_endpoint_blocked_in_production(self):
        """Test that the endpoint is blocked when not in test/debug/CI modes"""
        with override_settings(TEST=False, DEBUG=False, CI=False, E2E_TESTING=False):
            response = self.client.post("/api/setup_test/organization_with_team/", {})
            assert response.status_code == status.HTTP_404_NOT_FOUND

    @override_settings(TEST=True)
    def test_organization_with_team_setup(self):
        """Test the organization_with_team setup function"""
        payload = {"organization_name": "Test Org API"}

        response = self.client.post("/api/setup_test/organization_with_team/", payload, format="json")

        # Check response structure
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["success"]
        assert data["test_name"] == "organization_with_team"
        assert "result" in data

        result = data["result"]

        # Check all required fields are present
        required_fields = [
            "organization_id",
            "team_id",
            "user_id",
            "organization_name",
            "team_name",
            "user_email",
            "personal_api_key",
        ]
        for field in required_fields:
            assert field in result
            assert result[field] is not None

        # Verify the actual data matches what we requested
        assert result["organization_name"] == "Test Org API"

        # Verify database objects were created
        org = Organization.objects.get(id=result["organization_id"])
        assert org.name == "Test Org API"

        team = Team.objects.get(id=result["team_id"])
        assert team.organization == org

        user = User.objects.get(id=result["user_id"])

        # Verify API key was created and is valid
        api_key = PersonalAPIKey.objects.get(user=user)
        assert api_key.label == "Test API Key"
        assert "*" in api_key.scopes  # Should have full access
        assert result["personal_api_key"].startswith("phx_")

    @override_settings(DEBUG=True)
    def test_endpoint_allowed_in_debug_mode(self):
        """Test that the endpoint works in DEBUG mode"""
        payload = {"organization_name": "Debug Org"}
        response = self.client.post("/api/setup_test/organization_with_team/", payload, format="json")
        assert response.status_code == status.HTTP_200_OK

    @override_settings(E2E_TESTING=True)
    def test_endpoint_allowed_in_e2e_mode(self):
        """Test that the endpoint works in E2E_TESTING mode"""
        payload = {"organization_name": "E2E Org"}
        response = self.client.post("/api/setup_test/organization_with_team/", payload, format="json")
        assert response.status_code == status.HTTP_200_OK

    @override_settings(TEST=True)
    def test_unknown_setup_function(self):
        """Test handling of unknown setup function"""
        response = self.client.post("/api/setup_test/nonexistent_setup/", {}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert "not found" in data["error"]
        assert "available_tests" in data
        assert "organization_with_team" in data["available_tests"]

    @override_settings(TEST=True)
    def test_setup_with_defaults(self):
        """Test setup function with default parameters (empty payload)"""
        response = self.client.post("/api/setup_test/organization_with_team/", {}, format="json")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        result = data["result"]

        # Should use default values
        assert result["organization_name"] == "Hedgebox Inc."
