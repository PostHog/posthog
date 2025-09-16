import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.api.test.test_sharing import mock_exporter_template
from posthog.constants import AvailableFeature
from posthog.models import Dashboard, SharePassword, SharingConfiguration


class TestSharePasswordAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Enable advanced permissions feature for the organization
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ADVANCED_PERMISSIONS,
                "name": AvailableFeature.ADVANCED_PERMISSIONS,
            }
        ]
        self.organization.save()

        self.dashboard = Dashboard.objects.create(team=self.team, name="Test Dashboard", created_by=self.user)
        self.sharing_config = SharingConfiguration.objects.create(
            team=self.team, dashboard=self.dashboard, enabled=True, password_required=True
        )

    def test_create_password_with_custom_password(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/",
            data=json.dumps({"raw_password": "my-secure-password", "note": "Test password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        self.assertEqual(data["password"], "my-secure-password")
        self.assertEqual(data["note"], "Test password")
        self.assertEqual(data["created_by_email"], self.user.email)
        self.assertIn("id", data)
        self.assertIn("created_at", data)

        # Verify password was created in database
        share_password = SharePassword.objects.get(id=data["id"])
        self.assertTrue(share_password.check_password("my-secure-password"))
        self.assertEqual(share_password.note, "Test password")

    def test_create_password_with_generated_password(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/",
            data=json.dumps({"note": "Auto-generated password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        # Should have generated a secure password
        self.assertIsNotNone(data["password"])
        self.assertTrue(len(data["password"]) >= 16)
        self.assertEqual(data["note"], "Auto-generated password")

        # Verify password works
        share_password = SharePassword.objects.get(id=data["id"])
        self.assertTrue(share_password.check_password(data["password"]))

    def test_create_password_without_password_protection_enabled(self):
        # Disable password protection
        self.sharing_config.password_required = False
        self.sharing_config.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/",
            data=json.dumps({"raw_password": "test-password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Password protection must be enabled", response.json()["error"])

    def test_create_password_without_advanced_permissions(self):
        # Mock organization without advanced permissions
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/",
            data=json.dumps({"raw_password": "test-password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Advanced Permissions feature", response.json()["error"])

    def test_create_password_validation_too_short(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/",
            data=json.dumps({"raw_password": "short"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("at least 8 characters", str(response.json()))

    def test_delete_password(self):
        # Create a password first
        share_password, _ = SharePassword.create_password(
            sharing_configuration=self.sharing_config,
            created_by=self.user,
            raw_password="test-password",
            note="To be deleted",
        )

        response = self.client.delete(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/{share_password.id}/"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify password was deactivated
        share_password.refresh_from_db()
        self.assertFalse(share_password.is_active)

    def test_delete_nonexistent_password(self):
        response = self.client.delete(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/99999/"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("Password not found", response.json()["detail"])

    def test_delete_password_without_advanced_permissions(self):
        share_password, _ = SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="test-password"
        )

        # Mock organization without advanced permissions
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.delete(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/{share_password.id}/"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Advanced Permissions feature", response.json()["error"])

    def test_password_validation_in_sharing_viewer(self):
        """Test that password validation works correctly in the sharing viewer."""
        # Create a password
        share_password, raw_password = SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="secure-test-password"
        )

        # Test with correct password
        response = self.client.post(
            f"/shared/{self.sharing_config.access_token}",
            data=json.dumps({"password": raw_password}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("shareToken", response.json())

        # Test with incorrect password
        response = self.client.post(
            f"/shared/{self.sharing_config.access_token}",
            data=json.dumps({"password": "wrong-password"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Incorrect password", response.json()["error"])

    @mock_exporter_template
    def test_jwt_token_invalidation_on_password_deletion(self):
        """Test that JWT tokens are invalidated when their associated password is deleted, but remain valid when other passwords are deleted."""
        # Create two passwords
        password1, raw_password1 = SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="password1", note="Password 1"
        )
        password2, raw_password2 = SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="password2", note="Password 2"
        )

        # Authenticate with password1 to get JWT token
        response = self.client.post(
            f"/shared/{self.sharing_config.access_token}",
            data=json.dumps({"password": raw_password1}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        jwt_token1 = response.json()["shareToken"]

        # Authenticate with password2 to get another JWT token
        response = self.client.post(
            f"/shared/{self.sharing_config.access_token}",
            data=json.dumps({"password": raw_password2}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        jwt_token2 = response.json()["shareToken"]

        # Verify both JWT tokens work initially
        response = self.client.get(
            f"/shared/{self.sharing_config.access_token}",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token1}",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(
            f"/shared/{self.sharing_config.access_token}",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token2}",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Delete password2 (not the one used for jwt_token1)
        response = self.client.delete(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/{password2.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # jwt_token1 should still be valid since it was created with password1
        response = self.client.get(
            f"/shared/{self.sharing_config.access_token}",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token1}",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should contain dashboard data, not unlock page
        self.assertIn("dashboard", response.json())

        # jwt_token2 should now be invalid since password2 was deleted
        response = self.client.get(
            f"/shared/{self.sharing_config.access_token}",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token2}",
            HTTP_ACCEPT="application/json",
        )
        # Should not be authenticated anymore, so should show unlock page
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Since authentication failed, response is HTML with unlock page text
        response_text = response.content.decode("utf-8")
        self.assertIn('{"type": "unlock"}', response_text)

        # Now delete password1
        response = self.client.delete(
            f"/api/environments/{self.team.id}/dashboards/{self.dashboard.id}/sharing/passwords/{password1.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # jwt_token1 should now also be invalid
        response = self.client.get(
            f"/shared/{self.sharing_config.access_token}",
            HTTP_AUTHORIZATION=f"Bearer {jwt_token1}",
            HTTP_ACCEPT="application/json",
        )
        # Should not be authenticated anymore, so should show unlock page
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Since authentication failed, response is HTML with unlock page text
        response_text = response.content.decode("utf-8")
        self.assertIn('{"type": "unlock"}', response_text)

    @patch("posthog.rate_limit.is_rate_limit_enabled")
    def test_sharing_view_works_with_rate_limiting_enabled(self, mock_is_rate_limit_enabled):
        """
        Test that ensures sharing views work correctly when rate limiting is enabled.
        This test specifically verifies that request.user is properly set before throttle checks,
        preventing AttributeError: 'NoneType' object has no attribute 'is_authenticated'
        """
        # Force rate limiting to be enabled
        mock_is_rate_limit_enabled.return_value = True

        password, raw_password = SharePassword.create_password(
            sharing_configuration=self.sharing_config, created_by=self.user, raw_password="testpass123"
        )

        # Test that we can authenticate with password (this would fail with 500 error if request.user is None during throttle checks)
        response = self.client.post(
            f"/shared/{self.sharing_config.access_token}",
            data=json.dumps({"password": raw_password}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("shareToken", response.json())

        # Test that we can access the shared content (this would also fail if throttle checks break)
        response = self.client.get(f"/shared/{self.sharing_config.access_token}")
        # Should get unlock page (HTML response, not 500 error)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("text/html", response.get("Content-Type", ""))
