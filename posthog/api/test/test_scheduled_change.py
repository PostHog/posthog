from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import FeatureFlag, ScheduledChange


class TestScheduledChange(APIBaseTest):
    def test_can_create_flag_change(self):
        # Create a feature flag to schedule changes for
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="test-flag", name="Test Flag"
        )

        payload = {"field": "active", "value": "false"}

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "id": 6,
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": payload,
                "scheduled_at": "2023-12-08T12:00:00Z",
                "executed_at": None,
                "failure_reason": "",
            },
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert ScheduledChange.objects.filter(id=response_data["id"]).exists()
        assert response_data["model_name"] == "FeatureFlag"
        assert response_data["record_id"] == str(feature_flag.id)
        assert response_data["payload"] == payload
        assert response_data["created_by"]["id"] == self.user.id

    def test_cannot_create_scheduled_change_without_feature_flag_edit_permission(self):
        """Test that users without edit permissions cannot create scheduled changes for feature flags"""
        # Create a feature flag
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="test-flag", name="Test Flag"
        )

        payload = {"operation": "update_status", "value": False}

        # Mock the permission check to return False
        with patch("posthog.api.scheduled_change.CanEditFeatureFlag.has_object_permission", return_value=False):
            response = self.client.post(
                f"/api/projects/{self.team.id}/scheduled_changes/",
                data={
                    "record_id": str(feature_flag.id),
                    "model_name": "FeatureFlag",
                    "payload": payload,
                    "scheduled_at": "2023-12-08T12:00:00Z",
                },
            )

        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "You don't have edit permissions for this feature flag" in str(response_data)
        assert not ScheduledChange.objects.filter(record_id=str(feature_flag.id)).exists()

    def test_can_create_scheduled_change_with_feature_flag_edit_permission(self):
        """Test that users with edit permissions can create scheduled changes for feature flags"""
        # Create a feature flag
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="test-flag", name="Test Flag"
        )

        payload = {"operation": "update_status", "value": False}

        # Mock the permission check to return True
        with patch("posthog.api.scheduled_change.CanEditFeatureFlag.has_object_permission", return_value=True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/scheduled_changes/",
                data={
                    "record_id": str(feature_flag.id),
                    "model_name": "FeatureFlag",
                    "payload": payload,
                    "scheduled_at": "2023-12-08T12:00:00Z",
                },
            )

        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert ScheduledChange.objects.filter(record_id=str(feature_flag.id)).exists()
        assert response_data["model_name"] == "FeatureFlag"
        assert response_data["record_id"] == str(feature_flag.id)

    def test_cannot_create_scheduled_change_for_nonexistent_feature_flag(self):
        """Test that scheduled changes cannot be created for non-existent feature flags"""
        payload = {"operation": "update_status", "value": False}

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": "999999",  # Non-existent feature flag ID
                "model_name": "FeatureFlag",
                "payload": payload,
                "scheduled_at": "2023-12-08T12:00:00Z",
            },
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "Feature flag not found" in str(response_data)
        assert not ScheduledChange.objects.filter(record_id="999999").exists()
