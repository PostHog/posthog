"""Tests for materialized column slot activity logging."""

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from temporalio.testing import ActivityEnvironment

from posthog.models import ActivityLog, MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.temporal.backfill_materialized_property.activities import (
    ActivateSlotsInputs,
    FailSlotsInputs,
    activate_slots,
    fail_slots,
)

from products.event_definitions.backend.models.property_definition import PropertyType


class TestMaterializedColumnActivityLogging(APIBaseTest):
    """Activity logging contract for the PENDING-flow materialized column slot lifecycle."""

    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def test_activity_log_on_slot_creation(self):
        """assign_slot creates a slot and logs `materialized_column_created`."""
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

    def test_activity_log_on_retry(self):
        """retry_backfill puts the slot back into PENDING and logs the transition."""
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
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/materialized_column_slots/{slot.id}/retry_backfill/"
        )

        assert response.status_code == 200

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

        state_changes = [c for c in log.detail["changes"] if c["field"] == "state"]
        assert len(state_changes) == 1
        assert state_changes[0]["before"] == "ERROR"
        assert state_changes[0]["after"] == "PENDING"

        assert log.user == self.user

    @patch("posthog.api.materialized_column_slot.is_impersonated")
    def test_activity_log_includes_impersonation_flag(self, mock_is_impersonated):
        mock_is_impersonated.return_value = True

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

        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="DataManagement",
            activity="materialized_column_created",
        )

        assert activity_logs.count() == 1
        log = activity_logs.first()
        assert log is not None
        assert log.was_impersonated is True

    def test_activate_slots_logs_completion(self):
        """The new batched workflow's activate_slots activity logs a completion entry per slot."""
        activity_environment = ActivityEnvironment()
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="batched_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=7,
            state=MaterializedColumnSlotState.BACKFILL,
        )

        activity_environment.run(activate_slots, ActivateSlotsInputs(slot_ids=[str(slot.id)]))

        slot.refresh_from_db()
        assert slot.state == MaterializedColumnSlotState.READY

        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="DataManagement",
            activity="materialized_column_backfill_completed",
        )
        assert activity_logs.count() == 1
        log = activity_logs.first()
        assert log is not None and log.detail is not None
        assert log.detail["name"] == "batched_prop"

    def test_fail_slots_logs_failure(self):
        """fail_slots transitions slots to ERROR and logs `materialized_column_backfill_failed`."""
        activity_environment = ActivityEnvironment()
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="batched_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        slot = MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=7,
            state=MaterializedColumnSlotState.BACKFILL,
        )

        activity_environment.run(
            fail_slots,
            FailSlotsInputs(slot_ids=[str(slot.id)], error_message="ClickHouse OOM"),
        )

        slot.refresh_from_db()
        assert slot.state == MaterializedColumnSlotState.ERROR
        assert slot.error_message == "ClickHouse OOM"

        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="DataManagement",
            activity="materialized_column_backfill_failed",
        )
        assert activity_logs.count() == 1
