"""
Tests for deleting usage dashboards when feature flags are deleted.
"""

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Dashboard, FeatureFlag
from posthog.models.dashboard_tile import DashboardTile


class TestFeatureFlagDashboardDeletion(APIBaseTest):
    """Test cases for deleting dashboards with feature flags."""

    def setUp(self):
        super().setUp()
        FeatureFlag.objects.filter(team=self.team).delete()

    def test_delete_flag_without_dashboard_deletion_preserves_dashboard(self):
        """Test that dashboard is preserved when flag is deleted without the option."""
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

        dashboard = Dashboard.objects.get(id=dashboard_id)
        self.assertFalse(dashboard.deleted)

    def test_delete_flag_with_dashboard_deletion_deletes_dashboard(self):
        """Test that dashboard is soft-deleted when option is set."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "test-flag", "name": "Test", "_should_create_usage_dashboard": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        dashboard_id = response.json()["usage_dashboard"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/",
            {"deleted": True, "_should_delete_usage_dashboard": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        dashboard = Dashboard.objects_including_soft_deleted.get(id=dashboard_id)
        self.assertTrue(dashboard.deleted)

    def test_delete_flag_with_dashboard_deletion_deletes_insights(self):
        """Test that insights on the dashboard are soft-deleted."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "test-flag", "name": "Test", "_should_create_usage_dashboard": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        dashboard_id = response.json()["usage_dashboard"]

        tiles_before = list(DashboardTile.objects.filter(dashboard_id=dashboard_id))
        self.assertGreater(len(tiles_before), 0)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/",
            {"deleted": True, "_should_delete_usage_dashboard": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for tile in DashboardTile.objects_including_soft_deleted.filter(dashboard_id=dashboard_id):
            self.assertTrue(tile.deleted)
            if tile.insight:
                self.assertTrue(tile.insight.deleted)

    def test_delete_flag_without_dashboard_succeeds_with_delete_option(self):
        """Test deletion works when flag has no usage dashboard."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "test-flag", "name": "Test", "_should_create_usage_dashboard": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        self.assertIsNone(response.json()["usage_dashboard"])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/",
            {"deleted": True, "_should_delete_usage_dashboard": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

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

    def test_flag_usage_dashboard_cleared_after_deletion(self):
        """Test that the flag's usage_dashboard reference is cleared after deletion."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "test-flag", "name": "Test", "_should_create_usage_dashboard": True},
            format="json",
        )
        flag_id = response.json()["id"]
        dashboard_id = response.json()["usage_dashboard"]
        self.assertIsNotNone(dashboard_id)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/",
            {"deleted": True, "_should_delete_usage_dashboard": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        flag = FeatureFlag.objects.get(id=flag_id)
        self.assertIsNone(flag.usage_dashboard)

    def test_regular_update_ignores_delete_dashboard_field(self):
        """Test that _should_delete_usage_dashboard is ignored on non-delete updates."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "test-flag", "name": "Test", "_should_create_usage_dashboard": True},
            format="json",
        )
        flag_id = response.json()["id"]
        dashboard_id = response.json()["usage_dashboard"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/",
            {"name": "Updated Name", "_should_delete_usage_dashboard": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        dashboard = Dashboard.objects.get(id=dashboard_id)
        self.assertFalse(dashboard.deleted)

        flag = FeatureFlag.objects.get(id=flag_id)
        self.assertEqual(flag.usage_dashboard_id, dashboard_id)
