import uuid
import datetime as dt

import pytest
from unittest.mock import patch

import temporalio.worker
import temporalio.workflow
from temporalio import (
    activity as temporal_activity,
    workflow as temporal_workflow,
)
from temporalio.testing import WorkflowEnvironment

from posthog.temporal.data_modeling.activities import GetDAGStructureInputs
from posthog.temporal.data_modeling.activities.get_dag_structure import DAG as DAGPlan
from posthog.temporal.data_modeling.workflows.execute_dag import ExecuteDAGInputs, ExecuteDAGResult, ExecuteDAGWorkflow
from posthog.temporal.tests.data_modeling.test_execute_dag_workflow import (
    MockMaterializeViewWorkflow,
    _mock_workflow_should_block_on_quality,
    _mock_workflow_should_fail,
    _mock_workflow_should_self_audit,
    stub_notify_dag_materialization_failures,
    stub_preempt_dag_run,
    stub_record_skipped_data_modeling_jobs,
)

from products.data_quality.backend.facade.contracts import MATERIALIZATION_GATE_ACTIVITY_NAME

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

_suite_runs_started: list[dict] = []

_MOCK_STATE = (
    _suite_runs_started,
    _mock_workflow_should_fail,
    _mock_workflow_should_block_on_quality,
    _mock_workflow_should_self_audit,
)


@temporal_workflow.defn(name="data-quality-run-suite")
class MockCheckSuiteWorkflow:
    @temporal_workflow.run
    async def run(self, inputs: dict) -> dict:
        _suite_runs_started.append(inputs)
        return {"suite_run_id": "s-1", "status": "empty"}


class TestPostMaterializationChecks:
    @pytest.fixture(autouse=True)
    def reset_mock_state(self):
        for state in _MOCK_STATE:
            state.clear()
        yield
        for state in _MOCK_STATE:
            state.clear()

    async def _run_dag(
        self,
        team_id: int,
        node_ids: list[str],
        *,
        ephemeral_node_ids: list[str] | None = None,
        edges: list[tuple[str, str]] | None = None,
        register_suite: bool = True,
        checks_needed: bool = True,
    ) -> ExecuteDAGResult:
        executable = node_ids + (ephemeral_node_ids or [])

        @temporal_activity.defn(name="get_dag_structure_activity")
        async def stub_get_dag_structure(_: GetDAGStructureInputs) -> DAGPlan:
            return DAGPlan(
                nodes=executable,
                executable_nodes=executable,
                edges=edges or [],
                ephemeral_nodes=ephemeral_node_ids or [],
            )

        @temporal_activity.defn(name=MATERIALIZATION_GATE_ACTIVITY_NAME)
        async def stub_materialization_gate(_: dict) -> bool:
            return checks_needed

        workflows = [ExecuteDAGWorkflow, MockMaterializeViewWorkflow]
        if register_suite:
            workflows.append(MockCheckSuiteWorkflow)

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with temporalio.worker.Worker(
                env.client,
                task_queue="test-queue",
                workflows=workflows,
                activities=[
                    stub_preempt_dag_run,
                    stub_get_dag_structure,
                    stub_materialization_gate,
                    stub_record_skipped_data_modeling_jobs,
                    stub_notify_dag_materialization_failures,
                ],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                return await env.client.execute_workflow(
                    ExecuteDAGWorkflow.run,
                    ExecuteDAGInputs(team_id=team_id, dag_id="dag-1"),
                    id=f"test-data-quality-{uuid.uuid4()}",
                    task_queue="test-queue",
                    execution_timeout=dt.timedelta(seconds=30),
                )

    async def test_every_node_the_run_brought_up_to_date_is_handed_to_the_check_suite(self, ateam) -> None:
        materialized, failing, ephemeral = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        _mock_workflow_should_fail.add(failing)

        result = await self._run_dag(ateam.pk, [materialized, failing], ephemeral_node_ids=[ephemeral])

        assert result.successful_nodes == 2
        assert len(_suite_runs_started) == 1
        assert sorted(_suite_runs_started[0]["node_ids"]) == sorted([materialized, ephemeral])
        assert _suite_runs_started[0]["trigger"] == "materialization"
        assert _suite_runs_started[0]["team_id"] == ateam.pk

    async def test_no_suite_starts_when_nothing_materialized(self, ateam) -> None:
        failing = str(uuid.uuid4())
        _mock_workflow_should_fail.add(failing)

        result = await self._run_dag(ateam.pk, [failing])

        assert result.successful_nodes == 0
        assert _suite_runs_started == []

    async def test_no_suite_starts_when_the_gate_says_the_team_has_no_checks_to_run(self, ateam) -> None:
        result = await self._run_dag(ateam.pk, [str(uuid.uuid4())], checks_needed=False)

        assert result.successful_nodes == 1
        assert _suite_runs_started == []

    async def test_a_check_suite_that_cannot_start_does_not_fail_the_dag(self, ateam) -> None:
        result = await self._run_dag(ateam.pk, [str(uuid.uuid4())], register_suite=False)

        assert result.successful_nodes == 1
        assert result.failed_nodes == 0

    async def test_a_history_without_the_patch_marker_still_sweeps_every_node(self, ateam) -> None:
        # An old DAG worker records the gate activity and suite child against a new child's
        # quality_audited result. Filtering on replay would omit commands that history already has.
        audited = str(uuid.uuid4())
        _mock_workflow_should_self_audit.add(audited)

        with patch.object(temporalio.workflow, "patched", return_value=False):
            await self._run_dag(ateam.pk, [audited])

        assert len(_suite_runs_started) == 1
        assert _suite_runs_started[0]["node_ids"] == [audited]

    async def test_a_node_that_audited_itself_is_not_swept_again(self, ateam) -> None:
        audited, unaudited = str(uuid.uuid4()), str(uuid.uuid4())
        _mock_workflow_should_self_audit.add(audited)

        await self._run_dag(ateam.pk, [audited, unaudited])

        assert len(_suite_runs_started) == 1
        assert _suite_runs_started[0]["node_ids"] == [unaudited]

    async def test_a_blocked_publish_stops_its_descendants_and_leaves_the_sweep(self, ateam) -> None:
        blocked, downstream = str(uuid.uuid4()), str(uuid.uuid4())
        _mock_workflow_should_block_on_quality.add(blocked)

        result = await self._run_dag(ateam.pk, [blocked, downstream], edges=[(blocked, downstream)])

        assert result.failed_nodes == 1
        assert result.skipped_nodes == 1
        skipped = next(node for node in result.node_results if node.skipped)
        assert skipped.node_id == downstream
        assert skipped.skip_reason == f"Upstream node {blocked} failed data quality checks"
        assert _suite_runs_started == []
