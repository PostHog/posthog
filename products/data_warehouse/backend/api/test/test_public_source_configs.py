from posthog.test.base import APIBaseTest

from rest_framework import status


class TestPublicSourceConfigs(APIBaseTest):
    def test_list_returns_source_configs(self):
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.json(), list)
        assert len(response.json()) > 0

        first = response.json()[0]
        assert "name" in first
        assert "label" in first
        assert "iconPath" in first

    def test_does_not_expose_sensitive_fields(self):
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK

        for source in response.json():
            assert "fields" not in source
            assert "webhookFields" not in source

    def test_accessible_without_authentication(self):
        self.client.logout()
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.json(), list)
        assert len(response.json()) > 0

    def test_results_are_sorted_alphabetically(self):
        response = self.client.get("/api/public_source_configs/")
        assert response.status_code == status.HTTP_200_OK

        labels = [s.get("label") or s.get("name") or "" for s in response.json()]
        assert labels == sorted(labels, key=str.lower)
