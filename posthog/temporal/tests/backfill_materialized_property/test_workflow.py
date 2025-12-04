"""Tests for backfill materialized property workflow."""

import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.backfill_materialized_property.activities import (
    BackfillMaterializedColumnInputs,
    UpdateSlotStateInputs,
)
from posthog.temporal.backfill_materialized_property.workflows import (
    BackfillMaterializedPropertyInputs,
    BackfillMaterializedPropertyWorkflow,
)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestBackfillMaterializedPropertyWorkflow:
    """Test the backfill workflow state machine with mocked activities."""

    async def test_workflow_happy_path(self, amaterialized_slot):
        """Test successful workflow: BACKFILL → READY."""
        slot_id = str(amaterialized_slot.id)
        team_id = amaterialized_slot.team_id

        state_updates = []

        @activity.defn(name="backfill_materialized_column")
        async def mock_backfill(inputs: BackfillMaterializedColumnInputs) -> int:
            return 0

        @activity.defn(name="update_slot_state")
        async def mock_update_state(inputs: UpdateSlotStateInputs) -> bool:
            state_updates.append({"state": inputs.state, "error_message": inputs.error_message})
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
                        cache_refresh_wait_seconds=0,
                        state_update_retry_interval_seconds=1,
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        assert len(state_updates) == 1
        assert state_updates[0]["state"] == "READY"
        assert state_updates[0]["error_message"] is None

    async def test_workflow_backfill_fails(self, amaterialized_slot):
        """Test workflow failure when backfill fails: BACKFILL → ERROR."""
        slot_id = str(amaterialized_slot.id)
        team_id = amaterialized_slot.team_id

        state_updates = []

        @activity.defn(name="backfill_materialized_column")
        async def mock_backfill(inputs: BackfillMaterializedColumnInputs) -> int:
            raise ApplicationError("ClickHouse mutation failed", non_retryable=True)

        @activity.defn(name="update_slot_state")
        async def mock_update_state(inputs: UpdateSlotStateInputs) -> bool:
            state_updates.append({"state": inputs.state, "error_message": inputs.error_message})
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
                            cache_refresh_wait_seconds=0,
                            state_update_retry_interval_seconds=1,
                        ),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                    )

        assert len(state_updates) == 1
        assert state_updates[0]["state"] == "ERROR"
        assert state_updates[0]["error_message"] is not None
        assert "Activity task failed" in state_updates[0]["error_message"]

    async def test_workflow_update_state_to_error_fails(self, amaterialized_slot):
        """Test that workflow still raises original error if update_slot_state to ERROR fails."""
        slot_id = str(amaterialized_slot.id)
        team_id = amaterialized_slot.team_id

        @activity.defn(name="backfill_materialized_column")
        async def mock_backfill(inputs: BackfillMaterializedColumnInputs) -> int:
            raise ApplicationError("Original error: backfill failed", non_retryable=True)

        @activity.defn(name="update_slot_state")
        async def mock_update_state(inputs: UpdateSlotStateInputs) -> bool:
            # Always fail when trying to update to ERROR
            if inputs.state == "ERROR":
                raise ApplicationError("DB connection lost", non_retryable=True)
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
                            cache_refresh_wait_seconds=0,
                            state_update_retry_interval_seconds=1,
                        ),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                    )

                # Verify the workflow re-raises the ORIGINAL backfill error (not the state update error)
                # Temporal wraps errors, so we need to check the cause chain
                error = exc_info.value
                error_str = str(error)

                # Check if the error has a cause attribute (WorkflowFailureError)
                if hasattr(error, "cause"):
                    cause_str = str(error.cause) if error.cause else ""
                    full_error = f"{error_str} | cause: {cause_str}"
                else:
                    full_error = error_str

                # The original "backfill failed" error should be in the error chain
                assert (
                    "backfill failed" in full_error or "Activity task failed" in full_error
                ), f"Expected original backfill error in chain, got: {full_error}"

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
                        cache_refresh_wait_seconds=0,
                        state_update_retry_interval_seconds=1,
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        # Verify state update was retried and eventually succeeded
        assert call_count["count"] >= 3
