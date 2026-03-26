from posthog.test.base import APIBaseTest

from rest_framework import status


class TestPublicSourceConfigs(APIBaseTest):
    def test_list_returns_source_configs(self):
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert isinstance(data, dict)
        assert len(data) > 0

        first_config = next(iter(data.values()))
        assert "name" in first_config
        assert "label" in first_config
        assert "iconPath" in first_config
        assert "fields" in first_config

    def test_matches_wizard_response(self):
        """Public endpoint should return the same data as the authenticated /wizard endpoint."""
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK

        wizard_response = self.client.get("/api/environments/@current/external_data_sources/wizard/")
        assert wizard_response.status_code == status.HTTP_200_OK

        assert response.json() == wizard_response.json()

    def test_accessible_without_authentication(self):
        self.client.logout()
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert isinstance(data, dict)
        assert len(data) > 0
