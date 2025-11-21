"""Tests for backfill materialized property workflow state machine."""

import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState
from posthog.temporal.backfill_materialized_property.activities import (
    BackfillMaterializedColumnInputs,
    UpdateSlotStateInputs,
)
from posthog.temporal.backfill_materialized_property.workflows import (
    BackfillMaterializedPropertyInputs,
    BackfillMaterializedPropertyWorkflow,
)


@pytest.mark.django_db(transaction=True)
class TestBackfillMaterializedPropertyWorkflow:
    """Test the backfill workflow state machine with mocked activities."""

    @pytest.mark.asyncio
    async def test_workflow_happy_path(self, amaterialized_slot):
        """Test successful workflow: BACKFILL → READY."""
        slot_id = str(amaterialized_slot.id)
        team_id = amaterialized_slot.team_id

        @activity.defn(name="backfill_materialized_column")
        async def mock_backfill(inputs: BackfillMaterializedColumnInputs) -> int:
            return 0

        @activity.defn(name="update_slot_state")
        async def mock_update_state(inputs: UpdateSlotStateInputs) -> bool:
            slot = await MaterializedColumnSlot.objects.aget(id=slot_id)
            slot.state = inputs.state
            if inputs.error_message:
                slot.error_message = inputs.error_message
            await slot.asave()
            return True

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[BackfillMaterializedPropertyWorkflow],
                activities=[mock_backfill, mock_update_state],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    BackfillMaterializedPropertyWorkflow.run,
                    BackfillMaterializedPropertyInputs(
                        team_id=team_id,
                        slot_id=slot_id,
                        property_name="test_property",
                        property_type="String",
                        mat_column_name="dmat_string_0",
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        # Verify final state
        slot = await MaterializedColumnSlot.objects.aget(id=slot_id)
        assert slot.state == MaterializedColumnSlotState.READY
        assert slot.error_message is None

    @pytest.mark.asyncio
    async def test_workflow_backfill_fails(self, amaterialized_slot):
        """Test workflow failure when backfill fails: BACKFILL → ERROR."""
        slot_id = str(amaterialized_slot.id)
        team_id = amaterialized_slot.team_id

        @activity.defn(name="backfill_materialized_column")
        async def mock_backfill(inputs: BackfillMaterializedColumnInputs) -> int:
            raise RuntimeError("ClickHouse mutation failed")

        @activity.defn(name="update_slot_state")
        async def mock_update_state(inputs: UpdateSlotStateInputs) -> bool:
            slot = await MaterializedColumnSlot.objects.aget(id=slot_id)
            slot.state = inputs.state
            if inputs.error_message:
                slot.error_message = inputs.error_message
            await slot.asave()
            return True

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[BackfillMaterializedPropertyWorkflow],
                activities=[mock_backfill, mock_update_state],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                with pytest.raises(Exception):
                    await env.client.execute_workflow(
                        BackfillMaterializedPropertyWorkflow.run,
                        BackfillMaterializedPropertyInputs(
                            team_id=team_id,
                            slot_id=slot_id,
                            property_name="test_property",
                            property_type="String",
                            mat_column_name="dmat_string_0",
                        ),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                    )

        # Verify slot is in ERROR state
        slot = await MaterializedColumnSlot.objects.aget(id=slot_id)
        assert slot.state == MaterializedColumnSlotState.ERROR
        assert slot.error_message is not None
        assert "ClickHouse mutation failed" in slot.error_message

    @pytest.mark.asyncio
    async def test_workflow_update_state_to_ready_retries(self, amaterialized_slot):
        """Test that update_slot_state to READY retries on transient failures."""
        slot_id = str(amaterialized_slot.id)
        team_id = amaterialized_slot.team_id

        # Track how many times update_slot_state is called
        call_count = {"count": 0}

        @activity.defn(name="backfill_materialized_column")
        async def mock_backfill(inputs: BackfillMaterializedColumnInputs) -> int:
            return 0

        @activity.defn(name="update_slot_state")
        async def mock_update_state(inputs: UpdateSlotStateInputs) -> bool:
            call_count["count"] += 1
            # Fail first 2 attempts, succeed on 3rd
            if call_count["count"] < 3:
                raise RuntimeError("Transient database error")

            slot = await MaterializedColumnSlot.objects.aget(id=slot_id)
            slot.state = inputs.state
            if inputs.error_message:
                slot.error_message = inputs.error_message
            await slot.asave()
            return True

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[BackfillMaterializedPropertyWorkflow],
                activities=[mock_backfill, mock_update_state],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    BackfillMaterializedPropertyWorkflow.run,
                    BackfillMaterializedPropertyInputs(
                        team_id=team_id,
                        slot_id=slot_id,
                        property_name="test_property",
                        property_type="String",
                        mat_column_name="dmat_string_0",
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        # Verify state update was retried and eventually succeeded
        assert call_count["count"] >= 3
        slot = await MaterializedColumnSlot.objects.aget(id=slot_id)
        assert slot.state == MaterializedColumnSlotState.READY

    @pytest.mark.asyncio
    async def test_workflow_update_state_to_error_fails(self, amaterialized_slot):
        """Test that workflow still raises original error if update_slot_state to ERROR fails."""
        slot_id = str(amaterialized_slot.id)
        team_id = amaterialized_slot.team_id

        @activity.defn(name="backfill_materialized_column")
        async def mock_backfill(inputs: BackfillMaterializedColumnInputs) -> int:
            raise RuntimeError("Original error: backfill failed")

        @activity.defn(name="update_slot_state")
        async def mock_update_state(inputs: UpdateSlotStateInputs) -> bool:
            # Always fail when trying to update to ERROR
            if inputs.state == "ERROR":
                raise RuntimeError("DB connection lost")
            return True

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[BackfillMaterializedPropertyWorkflow],
                activities=[mock_backfill, mock_update_state],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                with pytest.raises(Exception) as exc_info:
                    await env.client.execute_workflow(
                        BackfillMaterializedPropertyWorkflow.run,
                        BackfillMaterializedPropertyInputs(
                            team_id=team_id,
                            slot_id=slot_id,
                            property_name="test_property",
                            property_type="String",
                            mat_column_name="dmat_string_0",
                        ),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                    )

                # Should raise the original error, not the state update error
                assert "backfill failed" in str(exc_info.value)
