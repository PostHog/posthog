"""Tests for the dmat batched workflows. Each test stubs every activity by registering
mocks under the real activity's `@activity.defn(name=...)` — renaming a real activity
therefore requires renaming its mock here too.
"""

import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.backfill_materialized_property.activities import (
    ActivateSlotsInputs,
    AssignPendingColumnsInputs,
    AssignPendingColumnsResult,
    FailSlotsInputs,
    PopulateSlotAssignmentsInputs,
    PopulateSlotAssignmentsResult,
    RunBatchedMutationInputs,
    _ColumnAssignment,
    _SlotBranch,
    compute_cycle_marker_int,
)
from posthog.temporal.backfill_materialized_property.workflows import (
    BackfillMaterializedPropertiesBatchInputs,
    BackfillMaterializedPropertiesBatchWorkflow,
)


@pytest.mark.asyncio
class TestBackfillMaterializedPropertiesBatchWorkflow:
    async def test_happy_path_assigns_runs_mutation_and_activates(self):
        recorded: dict[str, list] = {
            "assign": [],
            "populate": [],
            "mutation": [],
            "activate": [],
            "fail": [],
        }

        sample_assignments = [
            _ColumnAssignment(
                column_index=10,
                branches=[_SlotBranch(1, "browser", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")],
            )
        ]

        @activity.defn(name="assign_pending_columns")
        async def mock_assign(inputs: AssignPendingColumnsInputs) -> AssignPendingColumnsResult:
            recorded["assign"].append(inputs.run_id)
            return AssignPendingColumnsResult(
                assignments=sample_assignments,
                assigned_slot_ids=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
            )

        @activity.defn(name="populate_slot_assignments")
        async def mock_populate(inputs: PopulateSlotAssignmentsInputs) -> PopulateSlotAssignmentsResult:
            recorded["populate"].append(True)
            return PopulateSlotAssignmentsResult(rows_written=1)

        @activity.defn(name="run_batched_mutation")
        async def mock_run(inputs: RunBatchedMutationInputs) -> None:
            recorded["mutation"].append(
                {
                    "assignments": inputs.assignments,
                    "cycle_marker_int": inputs.cycle_marker_int,
                }
            )

        @activity.defn(name="activate_slots")
        async def mock_activate(inputs: ActivateSlotsInputs) -> int:
            recorded["activate"].append(inputs.slot_ids)
            return len(inputs.slot_ids)

        @activity.defn(name="fail_slots")
        async def mock_fail(inputs: FailSlotsInputs) -> int:
            recorded["fail"].append(inputs.slot_ids)
            return len(inputs.slot_ids)

        workflow_id = str(uuid.uuid4())
        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[BackfillMaterializedPropertiesBatchWorkflow],
                activities=[mock_assign, mock_populate, mock_run, mock_activate, mock_fail],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                handle = await env.client.start_workflow(
                    BackfillMaterializedPropertiesBatchWorkflow.run,
                    BackfillMaterializedPropertiesBatchInputs(cache_refresh_wait_seconds=0),
                    id=workflow_id,
                    task_queue=task_queue,
                )
                await handle.result()
                description = await handle.describe()
                run_id = description.run_id

        assert recorded["assign"], "assign activity should run"
        assert recorded["populate"] == [True], "populate activity should run between assign and mutation"
        assert len(recorded["mutation"]) == 1
        # cycle_marker_int passed through from run_id (NOT workflow_id).
        assert recorded["mutation"][0]["cycle_marker_int"] == compute_cycle_marker_int(run_id)
        assert recorded["mutation"][0]["assignments"] == [
            _ColumnAssignment(
                column_index=10,
                branches=[_SlotBranch(1, "browser", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")],
            )
        ]
        assert recorded["activate"] == [["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]]
        assert recorded["fail"] == []

    async def test_no_pending_slots_skips_mutation_and_activation(self):
        recorded: dict[str, list] = {"populate": [], "mutation": [], "activate": []}

        @activity.defn(name="assign_pending_columns")
        async def mock_assign(inputs: AssignPendingColumnsInputs) -> AssignPendingColumnsResult:
            return AssignPendingColumnsResult(assignments=[], assigned_slot_ids=[])

        @activity.defn(name="populate_slot_assignments")
        async def mock_populate(inputs: PopulateSlotAssignmentsInputs) -> PopulateSlotAssignmentsResult:
            recorded["populate"].append(True)
            return PopulateSlotAssignmentsResult(rows_written=0)

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
                activities=[mock_assign, mock_populate, mock_run, mock_activate, mock_fail],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    BackfillMaterializedPropertiesBatchWorkflow.run,
                    BackfillMaterializedPropertiesBatchInputs(cache_refresh_wait_seconds=0),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        # Workflow short-circuits before populate / mutation / activate when no PENDING slots.
        assert recorded["populate"] == []
        assert recorded["mutation"] == []
        assert recorded["activate"] == []

    async def test_mutation_failure_marks_slots_as_error(self):
        recorded: dict[str, list] = {"populate": [], "activate": [], "fail": []}

        sample_assignments = [
            _ColumnAssignment(
                column_index=10,
                branches=[_SlotBranch(1, "browser", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")],
            )
        ]

        @activity.defn(name="assign_pending_columns")
        async def mock_assign(inputs: AssignPendingColumnsInputs) -> AssignPendingColumnsResult:
            return AssignPendingColumnsResult(
                assignments=sample_assignments,
                assigned_slot_ids=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
            )

        @activity.defn(name="populate_slot_assignments")
        async def mock_populate(inputs: PopulateSlotAssignmentsInputs) -> PopulateSlotAssignmentsResult:
            recorded["populate"].append(True)
            return PopulateSlotAssignmentsResult(rows_written=1)

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
                activities=[mock_assign, mock_populate, mock_run, mock_activate, mock_fail],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                with pytest.raises(Exception):
                    await env.client.execute_workflow(
                        BackfillMaterializedPropertiesBatchWorkflow.run,
                        BackfillMaterializedPropertiesBatchInputs(cache_refresh_wait_seconds=0),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                    )

        # Populate ran (it precedes the mutation); failed slots got recorded; activate did NOT run.
        assert recorded["populate"] == [True]
        assert recorded["fail"], "fail_slots should have run"
        assert recorded["fail"][0][0] == ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]
        assert recorded["activate"] == []
