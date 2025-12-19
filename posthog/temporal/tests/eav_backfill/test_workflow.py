"""Tests for EAV property backfill workflow."""

import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.models.materialized_column_slots import MaterializedColumnSlotState
from posthog.temporal.eav_backfill.activities import BackfillEAVPropertyInputs, UpdateEAVSlotStateInputs
from posthog.temporal.eav_backfill.workflows import BackfillEAVPropertyWorkflow, BackfillEAVPropertyWorkflowInputs


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestBackfillEAVPropertyWorkflow:
    """Test the EAV backfill workflow state machine with mocked activities."""

    async def test_workflow_happy_path(self, aeav_slot):
        """Test successful workflow: BACKFILL → READY."""
        slot_id = str(aeav_slot.id)
        team_id = aeav_slot.team_id

        state_updates = []

        @activity.defn(name="backfill_eav_property")
        async def mock_backfill(inputs: BackfillEAVPropertyInputs) -> int:
            return 0

        @activity.defn(name="update_eav_slot_state")
        async def mock_update_state(inputs: UpdateEAVSlotStateInputs) -> bool:
            state_updates.append({"state": inputs.state, "error_message": inputs.error_message})
            return True

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[BackfillEAVPropertyWorkflow],
                activities=[mock_backfill, mock_update_state],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    BackfillEAVPropertyWorkflow.run,
                    BackfillEAVPropertyWorkflowInputs(
                        team_id=team_id,
                        slot_id=slot_id,
                        property_name="test_property",
                        property_type="String",
                        backfill_days=90,
                        cache_refresh_wait_seconds=0,
                        state_update_retry_interval_seconds=1,
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        assert len(state_updates) == 1
        assert state_updates[0]["state"] == MaterializedColumnSlotState.READY
        assert state_updates[0]["error_message"] is None

    async def test_workflow_backfill_fails(self, aeav_slot):
        """Test workflow failure when backfill fails: BACKFILL → ERROR."""
        slot_id = str(aeav_slot.id)
        team_id = aeav_slot.team_id

        state_updates = []

        @activity.defn(name="backfill_eav_property")
        async def mock_backfill(inputs: BackfillEAVPropertyInputs) -> int:
            raise ApplicationError("ClickHouse insert failed", non_retryable=True)

        @activity.defn(name="update_eav_slot_state")
        async def mock_update_state(inputs: UpdateEAVSlotStateInputs) -> bool:
            state_updates.append({"state": inputs.state, "error_message": inputs.error_message})
            return True

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[BackfillEAVPropertyWorkflow],
                activities=[mock_backfill, mock_update_state],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                with pytest.raises(Exception):
                    await env.client.execute_workflow(
                        BackfillEAVPropertyWorkflow.run,
                        BackfillEAVPropertyWorkflowInputs(
                            team_id=team_id,
                            slot_id=slot_id,
                            property_name="test_property",
                            property_type="String",
                            backfill_days=90,
                            cache_refresh_wait_seconds=0,
                            state_update_retry_interval_seconds=1,
                        ),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                    )

        assert len(state_updates) == 1
        assert state_updates[0]["state"] == MaterializedColumnSlotState.ERROR
        assert state_updates[0]["error_message"] is not None
        assert "Activity task failed" in state_updates[0]["error_message"]

    async def test_workflow_update_state_to_ready_retries(self, aeav_slot):
        """Test that update_eav_slot_state to READY retries on transient failures."""
        slot_id = str(aeav_slot.id)
        team_id = aeav_slot.team_id

        call_count = {"count": 0}

        @activity.defn(name="backfill_eav_property")
        async def mock_backfill(inputs: BackfillEAVPropertyInputs) -> int:
            return 0

        @activity.defn(name="update_eav_slot_state")
        async def mock_update_state(inputs: UpdateEAVSlotStateInputs) -> bool:
            call_count["count"] += 1
            # Fail first 2 attempts, succeed on 3rd
            if call_count["count"] < 3:
                raise RuntimeError("Transient database error")
            return True

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[BackfillEAVPropertyWorkflow],
                activities=[mock_backfill, mock_update_state],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    BackfillEAVPropertyWorkflow.run,
                    BackfillEAVPropertyWorkflowInputs(
                        team_id=team_id,
                        slot_id=slot_id,
                        property_name="test_property",
                        property_type="String",
                        backfill_days=90,
                        cache_refresh_wait_seconds=0,
                        state_update_retry_interval_seconds=1,
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        # Verify state update was retried and eventually succeeded
        assert call_count["count"] >= 3
