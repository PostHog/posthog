"""Tests for the BackfillMaterializedPropertiesBatchWorkflow (weekly batched flow)."""

import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.backfill_materialized_property.activities import (
    ActivateSlotsInputs,
    AssignPendingSlotsInputs,
    AssignPendingSlotsResult,
    FailSlotsInputs,
    RunBatchedMutationInputs,
    _ColumnAssignment,
)
from posthog.temporal.backfill_materialized_property.workflows import (
    BackfillMaterializedPropertiesBatchInputs,
    BackfillMaterializedPropertiesBatchWorkflow,
)


@pytest.mark.asyncio
class TestBackfillMaterializedPropertiesBatchWorkflow:
    async def test_happy_path_assigns_runs_mutation_and_activates(self):
        """Happy path: assign returns slots, mutation runs, activation runs once with all slot ids."""
        recorded: dict[str, list] = {"assign": [], "mutation": [], "activate": [], "fail": []}

        sample_assignments = [
            _ColumnAssignment(
                column_index=10,
                branches=[(1, "browser", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")],
            )
        ]

        @activity.defn(name="assign_pending_slots")
        async def mock_assign(inputs: AssignPendingSlotsInputs) -> AssignPendingSlotsResult:
            recorded["assign"].append(inputs.workflow_id)
            return AssignPendingSlotsResult(
                assignments=sample_assignments,
                assigned_slot_ids=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
                compacted_slot_ids=[],
            )

        @activity.defn(name="run_batched_mutation")
        async def mock_run(inputs: RunBatchedMutationInputs) -> None:
            recorded["mutation"].append([(a.column_index, a.branches) for a in inputs.assignments])

        @activity.defn(name="activate_slots")
        async def mock_activate(inputs: ActivateSlotsInputs) -> int:
            recorded["activate"].append(inputs.slot_ids)
            return len(inputs.slot_ids)

        @activity.defn(name="fail_slots")
        async def mock_fail(inputs: FailSlotsInputs) -> int:
            recorded["fail"].append(inputs.slot_ids)
            return len(inputs.slot_ids)

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[BackfillMaterializedPropertiesBatchWorkflow],
                activities=[mock_assign, mock_run, mock_activate, mock_fail],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    BackfillMaterializedPropertiesBatchWorkflow.run,
                    BackfillMaterializedPropertiesBatchInputs(cache_refresh_wait_seconds=0),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        assert recorded["assign"], "assign activity should run"
        assert recorded["mutation"] == [[(10, [(1, "browser", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")])]]
        assert recorded["activate"] == [["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]]
        assert recorded["fail"] == []

    async def test_no_pending_slots_skips_mutation_and_activation(self):
        recorded: dict[str, list] = {"mutation": [], "activate": []}

        @activity.defn(name="assign_pending_slots")
        async def mock_assign(inputs: AssignPendingSlotsInputs) -> AssignPendingSlotsResult:
            return AssignPendingSlotsResult(assignments=[], assigned_slot_ids=[], compacted_slot_ids=[])

        @activity.defn(name="run_batched_mutation")
        async def mock_run(inputs: RunBatchedMutationInputs) -> None:
            recorded["mutation"].append(True)

        @activity.defn(name="activate_slots")
        async def mock_activate(inputs: ActivateSlotsInputs) -> int:
            recorded["activate"].append(True)
            return 0

        @activity.defn(name="fail_slots")
        async def mock_fail(inputs: FailSlotsInputs) -> int:
            return 0

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[BackfillMaterializedPropertiesBatchWorkflow],
                activities=[mock_assign, mock_run, mock_activate, mock_fail],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    BackfillMaterializedPropertiesBatchWorkflow.run,
                    BackfillMaterializedPropertiesBatchInputs(cache_refresh_wait_seconds=0),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        assert recorded["mutation"] == []
        assert recorded["activate"] == []

    async def test_mutation_failure_marks_slots_as_error(self):
        """When the mutation activity fails, the workflow marks the assigned slots as ERROR."""
        recorded: dict[str, list] = {"activate": [], "fail": []}

        sample_assignments = [
            _ColumnAssignment(
                column_index=10,
                branches=[(1, "browser", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")],
            )
        ]

        @activity.defn(name="assign_pending_slots")
        async def mock_assign(inputs: AssignPendingSlotsInputs) -> AssignPendingSlotsResult:
            return AssignPendingSlotsResult(
                assignments=sample_assignments,
                assigned_slot_ids=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
                compacted_slot_ids=[],
            )

        @activity.defn(name="run_batched_mutation")
        async def mock_run(inputs: RunBatchedMutationInputs) -> None:
            raise ApplicationError("ClickHouse mutation timed out", non_retryable=True)

        @activity.defn(name="activate_slots")
        async def mock_activate(inputs: ActivateSlotsInputs) -> int:
            recorded["activate"].append(inputs.slot_ids)
            return len(inputs.slot_ids)

        @activity.defn(name="fail_slots")
        async def mock_fail(inputs: FailSlotsInputs) -> int:
            recorded["fail"].append((inputs.slot_ids, inputs.error_message))
            return len(inputs.slot_ids)

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[BackfillMaterializedPropertiesBatchWorkflow],
                activities=[mock_assign, mock_run, mock_activate, mock_fail],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                with pytest.raises(Exception):
                    await env.client.execute_workflow(
                        BackfillMaterializedPropertiesBatchWorkflow.run,
                        BackfillMaterializedPropertiesBatchInputs(cache_refresh_wait_seconds=0),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                    )

        # Failed slots got recorded; activate did NOT run.
        assert recorded["fail"], "fail_slots should have run"
        assert recorded["fail"][0][0] == ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]
        assert recorded["activate"] == []
