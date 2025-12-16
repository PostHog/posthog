"""Tests for materialized column slot activity logging."""

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from temporalio.testing import ActivityEnvironment

from posthog.models import ActivityLog, MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.models.property_definition import PropertyType
from posthog.temporal.backfill_materialized_property.activities import UpdateSlotStateInputs, update_slot_state


class TestMaterializedColumnActivityLogging(APIBaseTest):
    """Test that all state changes are properly logged."""

    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    @patch("posthog.api.materialized_column_slot.async_to_sync")
    def test_activity_log_on_slot_creation(self, mock_async_to_sync):
        """Test activity log created when slot assigned."""
        mock_async_to_sync.return_value = MagicMock(return_value="workflow-id-123")

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

        assert response.status_code == 201

        # Verify activity log was created
        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="DataManagement",
            activity="materialized_column_created",
        )

        assert activity_logs.count() == 1
        log = activity_logs.first()
        assert log is not None
        assert log.detail is not None
        assert log.detail["name"] == "test_prop"
        assert log.user == self.user

    def test_activity_log_on_slot_deletion(self):
        """Test activity log created when slot deleted."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            property_type=PropertyType.String,
            slot_index=5,
            state=MaterializedColumnSlotState.READY,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/materialized_column_slots/{slot.id}/")

        assert response.status_code == 204

        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="DataManagement",
            activity="materialized_column_deleted",
        )

        assert activity_logs.count() == 1
        log = activity_logs.first()
        assert log is not None
        assert log.detail is not None
        assert log.detail["name"] == "test_prop"

    def test_activity_log_on_backfill_completed(self):
        """Test activity log created when workflow completes successfully."""
        activity_environment = ActivityEnvironment()
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            property_type=PropertyType.String,
            slot_index=0,
            state=MaterializedColumnSlotState.BACKFILL,
        )

        # Call update_slot_state activity with READY
        activity_environment.run(
            update_slot_state,
            UpdateSlotStateInputs(slot_id=str(slot.id), state="READY"),
        )

        # Verify activity log was created
        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="DataManagement",
            activity="materialized_column_backfill_completed",
        )

        assert activity_logs.count() == 1
        log = activity_logs.first()
        assert log is not None
        assert log.detail is not None

        assert log.detail["name"] == "test_prop"

        # Verify state change is logged
        state_changes = [c for c in log.detail["changes"] if c["field"] == "state"]
        assert len(state_changes) == 1
        assert state_changes[0]["before"] == "BACKFILL"
        assert state_changes[0]["after"] == "READY"

        # User should be None (system user for workflow-triggered updates)
        assert log.user is None

    def test_activity_log_on_backfill_failed(self):
        """Test activity log created when workflow fails."""
        activity_environment = ActivityEnvironment()
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            property_type=PropertyType.String,
            slot_index=0,
            state=MaterializedColumnSlotState.BACKFILL,
        )

        # Call update_slot_state activity with ERROR
        activity_environment.run(
            update_slot_state,
            UpdateSlotStateInputs(
                slot_id=str(slot.id),
                state="ERROR",
                error_message="ClickHouse mutation failed",
            ),
        )

        # Verify activity log was created
        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="DataManagement",
            activity="materialized_column_backfill_failed",
        )

        assert activity_logs.count() == 1
        log = activity_logs.first()
        assert log is not None
        assert log.detail is not None

        assert log.detail["name"] == "test_prop"

        # Verify state change is logged
        state_changes = [c for c in log.detail["changes"] if c["field"] == "state"]
        assert len(state_changes) == 1
        assert state_changes[0]["before"] == "BACKFILL"
        assert state_changes[0]["after"] == "ERROR"

    def test_activity_log_no_log_for_backfill_state(self):
        """Test that transitioning to BACKFILL doesn't create activity log."""
        activity_environment = ActivityEnvironment()
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            property_type=PropertyType.String,
            slot_index=0,
            state=MaterializedColumnSlotState.ERROR,
        )

        initial_count = ActivityLog.objects.filter(team_id=self.team.id).count()

        # Call update_slot_state activity with BACKFILL
        activity_environment.run(
            update_slot_state,
            UpdateSlotStateInputs(slot_id=str(slot.id), state="BACKFILL"),
        )

        # Verify NO new activity log was created (only ERROR→READY and BACKFILL→ERROR/READY are logged)
        assert ActivityLog.objects.filter(team_id=self.team.id).count() == initial_count

    @patch("posthog.api.materialized_column_slot.async_to_sync")
    def test_activity_log_on_retry(self, mock_async_to_sync):
        """Test activity log created when backfill retried."""
        mock_async_to_sync.return_value = MagicMock(return_value="workflow-id-retry-123")

        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            property_type=PropertyType.String,
            slot_index=0,
            state=MaterializedColumnSlotState.ERROR,
            error_message="Previous error",
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/{slot.id}/retry_backfill/"
        )

        assert response.status_code == 200

        # Verify activity log was created
        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="DataManagement",
            activity="materialized_column_retried",
        )

        assert activity_logs.count() == 1
        log = activity_logs.first()
        assert log is not None
        assert log.detail is not None

        assert log.detail["name"] == "test_prop"

        # Verify state change from ERROR to BACKFILL
        state_changes = [c for c in log.detail["changes"] if c["field"] == "state"]
        assert len(state_changes) == 1
        assert state_changes[0]["before"] == "ERROR"
        assert state_changes[0]["after"] == "BACKFILL"

        # User should be set (user initiated retry)
        assert log.user == self.user

    @patch("posthog.api.materialized_column_slot.is_impersonated_session")
    @patch("posthog.api.materialized_column_slot.async_to_sync")
    def test_activity_log_includes_impersonation_flag(self, mock_async_to_sync, mock_is_impersonated):
        """Test that is_impersonated_session is captured."""
        mock_is_impersonated.return_value = True
        mock_async_to_sync.return_value = MagicMock(return_value="workflow-id-123")

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

        assert response.status_code == 201

        # Verify activity log has was_impersonated=True
        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="DataManagement",
            activity="materialized_column_created",
        )

        assert activity_logs.count() == 1
        log = activity_logs.first()
        assert log is not None

        assert log.was_impersonated is True
