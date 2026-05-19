from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
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

    @parameterized.expand(
        [
            (
                "update_status_allowed",
                "update_status",
                False,
                "daily",
                status.HTTP_201_CREATED,
            ),
            (
                "update_variants_allowed",
                "update_variants",
                {"variants": [{"key": "control", "rollout_percentage": 100}], "payloads": {}},
                "weekly",
                status.HTTP_201_CREATED,
            ),
            (
                "add_release_condition_blocked",
                "add_release_condition",
                {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "daily",
                status.HTTP_400_BAD_REQUEST,
            ),
        ]
    )
    def test_recurring_schedule_operation_validation(self, _name, operation, value, interval, expected_status):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="recurring-op-flag", name="Recurring Op Flag"
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": operation, "value": value},
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                "recurrence_interval": interval,
            },
        )

        response_data = response.json()
        assert response.status_code == expected_status, response_data

        if expected_status == status.HTTP_201_CREATED:
            assert response_data["is_recurring"] is True
            assert response_data["recurrence_interval"] == interval
        else:
            assert "not supported for add_release_condition" in str(response_data)

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

    def test_can_create_recurring_schedule_with_cron_expression(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="cron-flag", name="Cron Flag"
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": True},
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                "cron_expression": "0 9 * * 1-5",
            },
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["is_recurring"] is True
        assert response_data["cron_expression"] == "0 9 * * 1-5"
        assert response_data["recurrence_interval"] is None

    def test_rejects_both_cron_and_interval(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="both-flag", name="Both Flag"
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": True},
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                "cron_expression": "0 9 * * 1-5",
                "recurrence_interval": "daily",
            },
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "Cannot set both" in str(response_data)

    @parameterized.expand(
        [
            ("wrong_field_count", "not a cron", "5-field"),
            ("six_fields_rejected", "* * * * * *", "5-field"),
            ("invalid_syntax", "99 99 99 99 99", "Invalid cron expression"),
        ]
    )
    def test_rejects_invalid_cron_expression(self, _name, expr, expected_fragment):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="invalid-cron-flag", name="Invalid Cron Flag"
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": True},
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                "cron_expression": expr,
            },
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert expected_fragment in str(response_data)

    def test_non_recurring_rejects_cron_on_create(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="cron-non-recurring-flag", name="Cron Non-recurring Flag"
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": {"operation": "update_status", "value": True},
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": False,
                "cron_expression": "0 9 * * 1-5",
            },
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "cron_expression" in str(response_data)

    def test_cron_recurring_blocks_add_release_condition(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="cron-arc-flag", name="Cron ARC Flag"
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/scheduled_changes/",
            data={
                "record_id": str(feature_flag.id),
                "model_name": "FeatureFlag",
                "payload": {
                    "operation": "add_release_condition",
                    "value": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                },
                "scheduled_at": "2024-01-15T09:00:00Z",
                "is_recurring": True,
                "cron_expression": "0 9 * * 1-5",
            },
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data
        assert "not supported for add_release_condition" in str(response_data)

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

        with patch("posthog.api.scheduled_change.CanEditFeatureFlag.has_object_permission", return_value=True):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
                data={"payload": {"operation": "update_status", "value": True}},
            )

        assert response.status_code == status.HTTP_200_OK, response.json()

        scheduled_change.refresh_from_db()
        assert scheduled_change.payload == {"operation": "update_status", "value": True}

    @parameterized.expand(
        [
            ("denied_without_permission", False, status.HTTP_400_BAD_REQUEST, "You don't have edit permissions", False),
            ("allowed_with_permission", True, status.HTTP_200_OK, None, True),
        ]
    )
    def test_patch_respects_feature_flag_edit_permission(
        self, _name, has_permission, expected_status, expected_error_fragment, payload_should_change
    ):
        """PATCH must enforce CanEditFeatureFlag, matching the create-time check."""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key=f"perm-flag-{_name}", name="Perm Flag"
        )

        original_payload = {"operation": "update_status", "value": False}
        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload=original_payload,
            scheduled_at="2024-01-15T09:00:00Z",
            created_by=self.user,
        )

        new_payload = {"operation": "update_status", "value": True}
        with patch(
            "posthog.api.scheduled_change.CanEditFeatureFlag.has_object_permission", return_value=has_permission
        ):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
                data={"payload": new_payload},
            )

        assert response.status_code == expected_status, response.json()
        if expected_error_fragment:
            assert expected_error_fragment in str(response.json())

        scheduled_change.refresh_from_db()
        assert scheduled_change.payload == (new_payload if payload_should_change else original_payload)

    @parameterized.expand(
        [
            ("reset_executed_at", {"executed_at": None}),
            ("replace_payload", {"payload": {"operation": "update_status", "value": True}}),
            ("reschedule", {"scheduled_at": "2030-01-15T09:00:00Z"}),
        ]
    )
    def test_completed_one_time_scheduled_change_is_immutable(self, _name, patch_body):
        """A one-time schedule that already executed cannot be mutated — blocks replay + privilege escalation."""
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key=f"immutable-{_name}", name="Immutable Flag"
        )

        original_executed_at = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        original_payload = {"operation": "update_status", "value": False}
        original_scheduled_at = datetime(2024, 1, 15, 9, 0, 0, tzinfo=UTC)
        scheduled_change = ScheduledChange.objects.create(
            team=self.team,
            record_id=feature_flag.id,
            model_name="FeatureFlag",
            payload=original_payload,
            scheduled_at=original_scheduled_at,
            executed_at=original_executed_at,
            created_by=self.user,
        )

        with patch("posthog.api.scheduled_change.CanEditFeatureFlag.has_object_permission", return_value=True):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/scheduled_changes/{scheduled_change.id}/",
                data=patch_body,
            )

        # validate() rejects all mutations of a completed one-time schedule.
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "already executed" in str(response.json())

        scheduled_change.refresh_from_db()
        assert scheduled_change.executed_at == original_executed_at, (
            f"executed_at changed to {scheduled_change.executed_at} (status={response.status_code})"
        )
        assert scheduled_change.payload == original_payload, (
            f"payload changed to {scheduled_change.payload} (status={response.status_code})"
        )
        assert scheduled_change.scheduled_at == original_scheduled_at, (
            f"scheduled_at changed to {scheduled_change.scheduled_at} (status={response.status_code})"
        )
