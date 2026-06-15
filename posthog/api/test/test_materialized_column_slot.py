"""Tests for MaterializedColumnSlot REST API endpoints."""

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.models.materialized_column_slots import MAX_SLOTS_PER_TEAM

from products.event_definitions.backend.models.property_definition import PropertyType


class TestMaterializedColumnSlotAPI(APIBaseTest):
    """Test MaterializedColumnSlot REST API endpoints."""

    def setUp(self):
        super().setUp()
        # Make user staff so they can access endpoints
        self.user.is_staff = True
        self.user.save()

    def test_list_slots(self):
        """Test listing all slots for a team."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/materialized_column_slots/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1

    def test_list_slots_filtered_by_team(self):
        """Test that team_id query param filters correctly."""
        other_team = self.organization.teams.create(name="Other Team")
        prop_def = PropertyDefinition.objects.create(
            team=other_team,
            name="other_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=other_team,
            property_definition=prop_def,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/materialized_column_slots/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 0

    def test_slot_usage_empty(self):
        """Test slot usage when no slots are assigned."""
        response = self.client.get(f"/api/environments/{self.team.id}/materialized_column_slots/slot_usage/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["max_slots_per_team"] == MAX_SLOTS_PER_TEAM
        assert body["used_total"] == 0
        assert body["available"] == MAX_SLOTS_PER_TEAM

    def test_slot_usage_partially_filled(self):
        """Test slot usage with a mix of PENDING and READY slots."""
        for i in range(3):
            prop_def = PropertyDefinition.objects.create(
                team=self.team,
                name=f"prop_{i}",
                property_type=PropertyType.String,
                type=PropertyDefinition.Type.EVENT,
            )
            MaterializedColumnSlot.objects.create(
                team=self.team,
                property_definition=prop_def,
                slot_index=i if i == 2 else None,
                state=MaterializedColumnSlotState.READY if i == 2 else MaterializedColumnSlotState.PENDING,
            )

        response = self.client.get(f"/api/environments/{self.team.id}/materialized_column_slots/slot_usage/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["used_total"] == 3
        assert body["available"] == MAX_SLOTS_PER_TEAM - 3

    def test_slot_usage_all_slots_full(self):
        """Test slot usage when all slots are full."""
        for i in range(MAX_SLOTS_PER_TEAM):
            prop_def = PropertyDefinition.objects.create(
                team=self.team,
                name=f"prop_{i}",
                property_type=PropertyType.String,
                type=PropertyDefinition.Type.EVENT,
            )
            MaterializedColumnSlot.objects.create(
                team=self.team,
                property_definition=prop_def,
                slot_index=i,
                state=MaterializedColumnSlotState.READY,
            )

        response = self.client.get(f"/api/environments/{self.team.id}/materialized_column_slots/slot_usage/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["used_total"] == MAX_SLOTS_PER_TEAM
        assert body["available"] == 0

    def test_available_properties_filters_correctly(self):
        """Test that available_properties excludes the right properties."""
        # Create various property types
        PropertyDefinition.objects.create(
            team=self.team,
            name="custom_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="$feature/my_flag",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="$current_url",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="email",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.PERSON,
        )
        already_materialized = PropertyDefinition.objects.create(
            team=self.team,
            name="already_mat",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=already_materialized,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/materialized_column_slots/available_properties/")

        assert response.status_code == status.HTTP_200_OK
        prop_names = [p["name"] for p in response.json()]

        # Should include custom props and feature flags
        assert "custom_prop" in prop_names
        assert "$feature/my_flag" in prop_names

        # Should NOT include system props, person props, or already materialized
        assert "$current_url" not in prop_names
        assert "email" not in prop_names
        assert "already_mat" not in prop_names

    @patch("posthog.api.materialized_column_slot.get_auto_materialized_property_names")
    def test_available_properties_excludes_auto_materialized(self, mock_get_auto):
        """Test that auto-materialized properties are excluded from available_properties."""
        mock_get_auto.return_value = {"utm_source", "utm_medium"}

        PropertyDefinition.objects.create(
            team=self.team,
            name="utm_source",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="custom_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/materialized_column_slots/available_properties/")

        assert response.status_code == status.HTTP_200_OK
        prop_names = [p["name"] for p in response.json()]

        assert "custom_prop" in prop_names
        assert "utm_source" not in prop_names

    @patch("posthog.api.materialized_column_slot.get_materialized_columns")
    @patch("posthog.api.materialized_column_slot.EE_AVAILABLE", True)
    def test_auto_materialized_returns_only_properties_columns(self, mock_get_mat_cols):
        """Test that auto_materialized excludes person_properties columns."""
        mock_column = MagicMock()
        mock_column.name = "mat_$current_url"
        mock_column.details.property_name = "$current_url"
        mock_column.details.table_column = "properties"
        mock_column.details.is_disabled = False
        mock_column.is_nullable = True

        mock_person_column = MagicMock()
        mock_person_column.name = "mat_pp_$initial_utm_source"
        mock_person_column.details.property_name = "$initial_utm_source"
        mock_person_column.details.table_column = "person_properties"
        mock_person_column.details.is_disabled = False
        mock_person_column.is_nullable = True

        mock_get_mat_cols.return_value = {
            "mat_$current_url": mock_column,
            "mat_pp_$initial_utm_source": mock_person_column,
        }

        response = self.client.get(f"/api/environments/{self.team.id}/materialized_column_slots/auto_materialized/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        assert response.json()[0]["property_name"] == "$current_url"

    @patch("posthog.api.materialized_column_slot.EE_AVAILABLE", False)
    def test_auto_materialized_returns_empty_without_ee(self):
        """Test that auto_materialized returns [] when EE not available."""
        response = self.client.get(f"/api/environments/{self.team.id}/materialized_column_slots/auto_materialized/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_assign_slot_success(self):
        """Test successfully queueing a property as PENDING."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/assign_slot/",
            {"property_definition_id": prop_def.id},
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["state"] == "PENDING"
        assert body["slot_index"] is None

        slot = MaterializedColumnSlot.objects.get(property_definition=prop_def)
        assert slot.backfill_temporal_run_id is None

    def test_assign_slot_returns_error_when_all_slots_used(self):
        """Test error when team has reached MAX_SLOTS_PER_TEAM."""
        for i in range(MAX_SLOTS_PER_TEAM):
            prop_def = PropertyDefinition.objects.create(
                team=self.team,
                name=f"prop_{i}",
                property_type=PropertyType.String,
                type=PropertyDefinition.Type.EVENT,
            )
            MaterializedColumnSlot.objects.create(
                team=self.team,
                property_definition=prop_def,
                slot_index=i,
                state=MaterializedColumnSlotState.READY,
            )

        new_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="new_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/assign_slot/",
            {"property_definition_id": new_prop.id},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert f"maximum of {MAX_SLOTS_PER_TEAM}" in response.json()["error"]

    def test_assign_slot_no_property_type(self):
        """Test error when property has no type set."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="no_type_prop",
            property_type=None,
            type=PropertyDefinition.Type.EVENT,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/assign_slot/",
            {"property_definition_id": prop_def.id},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Property must have a type set" in response.json()["error"]

    @parameterized.expand(
        [
            [PropertyType.Numeric],
            [PropertyType.Boolean],
            [PropertyType.Datetime],
            [PropertyType.Duration],
            [PropertyType.String],
        ]
    )
    def test_assign_slot_accepts_all_typed_properties(self, prop_type):
        """All PropertyTypes are materializable — storage is `Nullable(String)`, HogQL casts at read time."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name=f"{prop_type}_prop",
            property_type=prop_type,
            type=PropertyDefinition.Type.EVENT,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/assign_slot/",
            {"property_definition_id": prop_def.id},
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()

    def test_assign_slot_system_property(self):
        """Test error when trying to materialize PostHog system property."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="$current_url",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/assign_slot/",
            {"property_definition_id": prop_def.id},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "PostHog system properties cannot be materialized" in response.json()["error"]

    def test_assign_slot_allows_feature_flags(self):
        """Test that feature flag properties CAN be materialized."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="$feature/my_flag",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/assign_slot/",
            {"property_definition_id": prop_def.id},
        )

        assert response.status_code == status.HTTP_201_CREATED

    @patch("posthog.api.materialized_column_slot.get_auto_materialized_property_names")
    def test_assign_slot_auto_materialized_property(self, mock_get_auto):
        """Test error when trying to materialize already auto-materialized property."""
        mock_get_auto.return_value = {"utm_source"}

        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="utm_source",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/assign_slot/",
            {"property_definition_id": prop_def.id},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already auto-materialized by PostHog" in response.json()["error"]

    def test_assign_slot_already_materialized(self):
        """Test error when property is already materialized."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="already_mat",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/assign_slot/",
            {"property_definition_id": prop_def.id},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Property is already materialized" in response.json()["error"]

    def test_retry_backfill_success(self):
        """Test retrying a failed backfill resets slot to PENDING."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=0,
            state=MaterializedColumnSlotState.ERROR,
            error_message="Previous error",
            backfill_temporal_run_id="failed-wf-1",
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/{slot.id}/retry_backfill/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["state"] == "PENDING"

        slot.refresh_from_db()
        assert slot.state == MaterializedColumnSlotState.PENDING
        assert slot.slot_index is None
        assert slot.error_message is None
        assert slot.backfill_temporal_run_id is None

    @parameterized.expand([["PENDING"], ["BACKFILL"], ["READY"]])
    def test_retry_backfill_rejects_non_error_states(self, current_state):
        """Test that retry only works on ERROR state."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=None if current_state == "PENDING" else 0,
            state=current_state,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/{slot.id}/retry_backfill/"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Can only retry slots in ERROR state" in response.json()["error"]

    def test_delete_slot(self):
        """Test deleting a slot."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/materialized_column_slots/{slot.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify slot was deleted
        assert not MaterializedColumnSlot.objects.filter(id=slot.id).exists()

    def test_delete_slot_blocked_during_backfill(self):
        """Test that deletion is blocked when backfill in progress."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=0,
            state=MaterializedColumnSlotState.BACKFILL,  # In progress!
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/materialized_column_slots/{slot.id}/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Cannot delete slot while backfill is in progress" in response.json()["error"]

        # Verify slot still exists
        assert MaterializedColumnSlot.objects.filter(id=slot.id).exists()

    @parameterized.expand(
        [
            ["PENDING", None],
            ["READY", 1],
            ["ERROR", 2],
        ]
    )
    def test_delete_slot_allowed_in_non_backfill_states(self, state, slot_index):
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name=f"test_prop_{state.lower()}",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        kwargs = {"error_message": "Previous failure"} if state == "ERROR" else {}
        slot = MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=slot_index,
            state=state,
            **kwargs,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/materialized_column_slots/{slot.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not MaterializedColumnSlot.objects.filter(id=slot.id).exists()

    def test_endpoints_require_staff_permission(self):
        """Test that non-staff users cannot access endpoints."""
        # Make user non-staff
        self.user.is_staff = False
        self.user.save()

        endpoints = [
            f"/api/environments/{self.team.id}/materialized_column_slots/",
            f"/api/environments/{self.team.id}/materialized_column_slots/slot_usage/",
            f"/api/environments/{self.team.id}/materialized_column_slots/available_properties/",
            f"/api/environments/{self.team.id}/materialized_column_slots/auto_materialized/",
        ]

        for endpoint in endpoints:
            response = self.client.get(endpoint)
            assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("posthog.permissions.is_impersonated_session")
    def test_endpoints_allow_impersonated_sessions(self, mock_is_impersonated):
        """Test that impersonated sessions can access endpoints."""
        mock_is_impersonated.return_value = True

        # Make user non-staff
        self.user.is_staff = False
        self.user.save()

        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )

        # Should succeed because of impersonated session
        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/assign_slot/",
            {"property_definition_id": prop_def.id},
        )

        assert response.status_code == status.HTTP_201_CREATED
