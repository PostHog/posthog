from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import serializers, status

from posthog.api.scheduled_change import ScheduledChangeSerializer
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

    def test_recurring_schedule_requires_interval(self):
        """Test that recurring schedules require a recurrence_interval"""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="recurring-test-flag", name="Recurring Test Flag"
        )

        payload = {"operation": "update_status", "value": True}

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": payload,
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                # Missing recurrence_interval
            },
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "recurrence_interval" in str(response_data)
        assert "required when is_recurring is true" in str(response_data)

    def test_recurring_schedule_only_allows_update_status_operation(self):
        """Test that recurring schedules only support the update_status operation"""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="recurring-op-test-flag", name="Recurring Op Test Flag"
        )

        # Try with add_release_condition operation
        payload = {
            "operation": "add_release_condition",
            "value": {"groups": [{"properties": [], "rollout_percentage": 100}]},
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": payload,
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                "recurrence_interval": "daily",
            },
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "Recurring schedules only support the update_status operation" in str(response_data)

    def test_can_create_valid_recurring_schedule(self):
        """Test that valid recurring schedules can be created"""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="valid-recurring-flag", name="Valid Recurring Flag"
        )

        payload = {"operation": "update_status", "value": False}

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": payload,
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                "recurrence_interval": "weekly",
            },
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["is_recurring"] is True
        assert response_data["recurrence_interval"] == "weekly"
        assert ScheduledChange.objects.filter(id=response_data["id"]).exists()

        # Verify the stored record
        scheduled_change = ScheduledChange.objects.get(id=response_data["id"])
        assert scheduled_change.is_recurring is True
        assert scheduled_change.recurrence_interval == "weekly"

    def test_non_recurring_schedule_rejects_interval(self):
        """Test that new non-recurring schedules cannot have recurrence_interval set"""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="non-recurring-flag", name="Non Recurring Flag"
        )

        payload = {"operation": "update_status", "value": True}

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": payload,
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": False,
                "recurrence_interval": "daily",  # Should be rejected
            },
        )

        response_data = response.json()

        # Creating with is_recurring=False and recurrence_interval set is not allowed
        # This prevents accidentally creating "paused" recurring schedules
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "recurrence_interval" in response_data.get("attr", "")

    def test_recurring_schedule_appears_in_list(self):
        """Test that recurring schedules are returned with correct fields in list endpoint"""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="list-recurring-flag", name="List Recurring Flag"
        )

        ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at="2024-01-15T09:00:00Z",
            is_recurring=True,
            recurrence_interval="monthly",
            created_by=self.user,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={"model_name": "FeatureFlag", "record_id": str(feature_flag.id)},
        )

        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["count"] == 1
        result = response_data["results"][0]
        assert result["is_recurring"] is True
        assert result["recurrence_interval"] == "monthly"

    def test_cannot_update_record_id(self):
        """Updating record_id is rejected to prevent cross-tenant manipulation."""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="immutable-target-flag", name="Immutable Target Flag"
        )
        other_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="other-flag", name="Other Flag"
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at="2024-01-15T09:00:00Z",
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
            data={"record_id": str(other_flag.id)},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "Cannot change the target record" in str(response.json())

        scheduled_change.refresh_from_db()
        assert str(scheduled_change.record_id) == str(feature_flag.id)

    def test_cannot_update_model_name_to_invalid_value(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="immutable-model-flag", name="Immutable Model Flag"
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at="2024-01-15T09:00:00Z",
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
            data={"model_name": "SomeOtherModel"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "model_name" in str(response.json())

        scheduled_change.refresh_from_db()
        assert scheduled_change.model_name == "FeatureFlag"

    def test_validate_rejects_model_name_change_on_update(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="validate-model-flag", name="Validate Model Flag"
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at="2024-01-15T09:00:00Z",
            created_by=self.user,
        )

        serializer = ScheduledChangeSerializer(instance=scheduled_change)
        with self.assertRaises(serializers.ValidationError) as ctx:
            serializer.validate({"model_name": "SomeFutureModel"})
        assert "Cannot change the model type" in str(ctx.exception)

    def test_cannot_update_record_id_via_put(self):
        feature_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="put-flag", name="Put Flag")
        other_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="other-put-flag", name="Other Put Flag"
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at="2024-01-15T09:00:00Z",
            created_by=self.user,
        )

        response = self.client.put(
            f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
            data={
                "record_id": str(other_flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": False},
                "scheduled_at": "2024-01-15T09:00:00Z",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "Cannot change the target record" in str(response.json())

        scheduled_change.refresh_from_db()
        assert str(scheduled_change.record_id) == str(feature_flag.id)

    def test_can_update_other_fields_without_changing_record_id(self):
        """Non-target fields like payload and scheduled_at can still be updated."""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="updatable-flag", name="Updatable Flag"
        )

        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload={"operation": "update_status", "value": False},
            scheduled_at="2024-01-15T09:00:00Z",
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
            data={"payload": {"operation": "update_status", "value": True}},
        )

        assert response.status_code == status.HTTP_200_OK, response.json()

        scheduled_change.refresh_from_db()
        assert scheduled_change.payload == {"operation": "update_status", "value": True}
