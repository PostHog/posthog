from posthog.test.base import APIBaseTest

from rest_framework import status

from products.browser_lab_testing.backend.models import BrowserLabTest


class TestBrowserLabTestSecretsAPI(APIBaseTest):
    def test_create_with_secrets(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/browser_lab_tests/",
            {"name": "Test", "url": "https://example.com", "steps": [], "secrets": {"API_KEY": "sk-123"}},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["secrets"] == {"API_KEY": {"secret": True}}

        lab_test = BrowserLabTest.objects.get(id=data["id"])
        assert lab_test.encrypted_secrets == {"API_KEY": "sk-123"}

    def test_create_without_secrets(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/browser_lab_tests/",
            {"name": "Test", "url": "https://example.com", "steps": []},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["secrets"] == {}

    def test_get_masks_secrets(self):
        lab_test = BrowserLabTest.objects.create(
            team=self.team,
            name="Test",
            url="https://example.com",
            encrypted_secrets={"TOKEN": "secret-value"},
        )

        response = self.client.get(f"/api/environments/{self.team.id}/browser_lab_tests/{lab_test.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["secrets"] == {"TOKEN": {"secret": True}}

    def test_update_preserves_secrets(self):
        lab_test = BrowserLabTest.objects.create(
            team=self.team,
            name="Test",
            url="https://example.com",
            encrypted_secrets={"TOKEN": "original-value"},
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/browser_lab_tests/{lab_test.id}/",
            {"secrets": {"TOKEN": {"secret": True}}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        lab_test.refresh_from_db()
        assert lab_test.encrypted_secrets == {"TOKEN": "original-value"}

    def test_update_replaces_secret(self):
        lab_test = BrowserLabTest.objects.create(
            team=self.team,
            name="Test",
            url="https://example.com",
            encrypted_secrets={"TOKEN": "old-value"},
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/browser_lab_tests/{lab_test.id}/",
            {"secrets": {"TOKEN": "new-value"}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        lab_test.refresh_from_db()
        assert lab_test.encrypted_secrets == {"TOKEN": "new-value"}
