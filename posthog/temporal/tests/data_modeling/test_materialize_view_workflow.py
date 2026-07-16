import pytest
from unittest.mock import AsyncMock, patch

import temporalio.workflow
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.data_modeling.activities import (
    FailMaterializationInputs,
    SucceedMaterializationResult,
    fail_materialization_activity,
)
from posthog.temporal.data_modeling.activities.enrich_view_semantics import EnrichViewSemanticsInputs
from posthog.temporal.data_modeling.workflows.materialize_view import (
    MaterializeViewWorkflow,
    MaterializeViewWorkflowInputs,
)

pytestmark = pytest.mark.asyncio

WORKFLOW_MODULE = "posthog.temporal.data_modeling.workflows.materialize_view"


def _inputs() -> MaterializeViewWorkflowInputs:
    return MaterializeViewWorkflowInputs(team_id=7, dag_id="dag-1", node_id="node-1")


class TestFinalizeOrphanedDuckgresJob:
    async def test_marks_orphaned_job_failed_without_touching_node(self):
        workflow = MaterializeViewWorkflow()
        with patch.object(temporalio.workflow, "execute_activity", new=AsyncMock()) as execute_activity:
            await workflow._finalize_orphaned_duckgres_job("job-123", _inputs(), "activity died")

        execute_activity.assert_awaited_once()
        assert execute_activity.await_args is not None
        activity, payload = execute_activity.await_args.args
        assert activity is fail_materialization_activity
        assert isinstance(payload, FailMaterializationInputs)
        assert payload.job_id == "job-123"
        # shadow job has no node properties to update — only finalize the job row
        assert payload.update_node is False
        assert "activity died" in payload.error

    async def test_noop_when_no_duckgres_job(self):
        workflow = MaterializeViewWorkflow()
        with patch.object(temporalio.workflow, "execute_activity", new=AsyncMock()) as execute_activity:
            await workflow._finalize_orphaned_duckgres_job(None, _inputs(), "activity died")
        execute_activity.assert_not_awaited()

    async def test_finalization_is_best_effort(self):
        workflow = MaterializeViewWorkflow()
        with (
            patch.object(temporalio.workflow, "execute_activity", new=AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(temporalio.workflow, "logger"),
        ):
            # a failure to finalize must never propagate out of the shadow path
            await workflow._finalize_orphaned_duckgres_job("job-123", _inputs(), "activity died")


class TestMaybeEnrichViewSemantics:
    async def test_starts_child_when_enrichment_needed(self):
        workflow = MaterializeViewWorkflow()
        result = SucceedMaterializationResult(enrichment_needed=True, saved_query_id="sq-1")
        with patch.object(temporalio.workflow, "start_child_workflow", new=AsyncMock()) as start_child:
            await workflow._maybe_enrich_view_semantics(_inputs(), result)

        start_child.assert_awaited_once()
        assert start_child.await_args is not None
        _wf_run, payload = start_child.await_args.args
        assert isinstance(payload, EnrichViewSemanticsInputs)
        assert payload.saved_query_id == "sq-1"
        assert payload.team_id == 7
        assert start_child.await_args.kwargs["id"] == "enrich-view-semantics-sq-1"

    @pytest.mark.parametrize(
        "result",
        [
            None,  # in-flight run on the pre-deploy activity version
            SucceedMaterializationResult(enrichment_needed=False, saved_query_id="sq-1"),
            SucceedMaterializationResult(enrichment_needed=True, saved_query_id=None),
        ],
    )
    async def test_no_child_when_not_needed(self, result):
        workflow = MaterializeViewWorkflow()
        with patch.object(temporalio.workflow, "start_child_workflow", new=AsyncMock()) as start_child:
            await workflow._maybe_enrich_view_semantics(_inputs(), result)
        start_child.assert_not_awaited()

    async def test_already_started_is_swallowed(self):
        # A concurrent trigger colliding on the shared workflow id must never fail the materialization.
        workflow = MaterializeViewWorkflow()
        result = SucceedMaterializationResult(enrichment_needed=True, saved_query_id="sq-1")
        with (
            patch.object(
                temporalio.workflow,
                "start_child_workflow",
                new=AsyncMock(side_effect=WorkflowAlreadyStartedError("enrich-view-semantics-sq-1", "type")),
            ),
            patch.object(temporalio.workflow, "logger"),
        ):
            await workflow._maybe_enrich_view_semantics(_inputs(), result)


class TestCollectShadowComparison:
    async def test_finalizes_orphaned_job_when_shadow_handle_errors(self):
        workflow = MaterializeViewWorkflow()

        async def dead_handle():
            raise RuntimeError("shadow activity died before finalizing")

        with (
            patch.object(temporalio.workflow, "execute_activity", new=AsyncMock()) as execute_activity,
            patch.object(temporalio.workflow, "logger"),
            patch(f"{WORKFLOW_MODULE}.capture_exception"),
            patch(f"{WORKFLOW_MODULE}.get_duckgres_shadow_finished_metric"),
        ):
            await workflow._collect_shadow_comparison(dead_handle(), "job-123", 5, 1.0, _inputs())

        # the activity died without self-finalizing, so the workflow must back it up
        execute_activity.assert_awaited_once()
        assert execute_activity.await_args is not None
        activity, payload = execute_activity.await_args.args
        assert activity is fail_materialization_activity
        assert payload.job_id == "job-123"
        assert payload.update_node is False
