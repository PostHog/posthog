"""
Tests for feature flag usage dashboard creation behavior.
"""

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import FeatureFlag


class TestFeatureFlagUsageDashboard(APIBaseTest):
    """Test cases for usage dashboard creation with feature flags."""

    def setUp(self):
        super().setUp()
        FeatureFlag.objects.filter(team=self.team).delete()

    def test_create_flag_creates_dashboard_by_default(self):
        """Test that dashboard is created by default when field is not specified."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "test-flag", "name": "Test"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(response.json()["usage_dashboard"])

    def test_create_flag_without_dashboard_when_explicitly_disabled(self):
        """Test that dashboard is not created when explicitly disabled via API."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "test-flag", "name": "Test", "_should_create_usage_dashboard": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.json()["usage_dashboard"])

    def test_delete_flag_preserves_dashboard(self):
        """Test that dashboard is preserved when flag is deleted (frontend handles dashboard deletion separately)."""
        from posthog.models import Dashboard

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "test-flag", "name": "Test", "_should_create_usage_dashboard": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        dashboard_id = response.json()["usage_dashboard"]
        self.assertIsNotNone(dashboard_id)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/",
            {"deleted": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Dashboard is preserved - frontend should handle deletion via dashboard API if needed
        dashboard = Dashboard.objects.get(id=dashboard_id)
        self.assertFalse(dashboard.deleted)
