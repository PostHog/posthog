import datetime as dt
from contextlib import ExitStack

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import temporalio.workflow
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.data_modeling.activities import (
    FailMaterializationInputs,
    MaterializeViewResult,
    PrepareQueryableTableResult,
    StageQueryableFilesResult,
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


def _materialize_result(quality_audit: str) -> MaterializeViewResult:
    return MaterializeViewResult(
        node_id="node-1",
        node_name="orders",
        row_count=10,
        table_uri="s3://bucket/orders",
        file_uris=["s3://bucket/orders/part-1.parquet"],
        saved_query_id="sq-1",
        quality_audit=quality_audit,
    )


class TestQualityGateBranching:
    async def _run(self, activity_results: list, child_result: dict) -> tuple:
        execute_activity = AsyncMock(side_effect=activity_results)
        info = MagicMock()
        info.parent = None
        with ExitStack() as stack:
            stack.enter_context(patch.object(temporalio.workflow, "execute_activity", new=execute_activity))
            stack.enter_context(
                patch.object(temporalio.workflow, "execute_child_workflow", new=AsyncMock(return_value=child_result))
            )
            stack.enter_context(patch.object(temporalio.workflow, "start_child_workflow", new=AsyncMock()))
            stack.enter_context(patch.object(temporalio.workflow, "info", return_value=info))
            stack.enter_context(patch.object(temporalio.workflow, "now", return_value=dt.datetime(2026, 8, 1)))
            stack.enter_context(patch.object(temporalio.workflow, "logger"))
            for metric in (
                "get_node_finished_metric",
                "get_node_duration_metric",
                "get_node_rows_materialized_metric",
                "get_node_storage_delta_mib_metric",
                "get_node_total_storage_mib_metric",
            ):
                stack.enter_context(patch(f"{WORKFLOW_MODULE}.{metric}"))
            result = await MaterializeViewWorkflow().run(_inputs())
        return result, execute_activity

    async def test_blocking_failures_stop_the_publish(self):
        activity_results = [
            False,  # duckgres shadow check
            "job-1",  # create job
            _materialize_result("gate"),
            StageQueryableFilesResult(folder_path="staged_1"),
            None,  # quality_block_materialization
        ]

        result, execute_activity = await self._run(activity_results, {"checks_failed_blocking": 2})

        assert result.quality_blocking_failures == 2
        assert result.quality_audited is True
        started = [call.args[0].__name__ for call in execute_activity.await_args_list]
        assert started[-2:] == ["stage_queryable_files_activity", "quality_block_materialization_activity"]
        assert "publish_queryable_table_activity" not in started
        assert "succeed_materialization_activity" not in started

    async def test_a_passing_audit_publishes_and_succeeds(self):
        activity_results = [
            False,
            "job-1",
            _materialize_result("gate"),
            StageQueryableFilesResult(folder_path="staged_1"),
            PrepareQueryableTableResult(storage_delta_mib=None, total_storage_mib=None),  # publish
            None,  # succeed (pre-deploy shape is fine, enrichment skipped)
        ]

        result, execute_activity = await self._run(activity_results, {"checks_failed_blocking": 0})

        assert result.quality_blocking_failures == 0
        started = [call.args[0].__name__ for call in execute_activity.await_args_list]
        assert "publish_queryable_table_activity" in started
        assert "succeed_materialization_activity" in started


class TestRunStagedAudit:
    async def test_reads_the_blocking_count_from_the_suite_result(self):
        workflow = MaterializeViewWorkflow()
        child = AsyncMock(return_value={"suite_run_id": "s-1", "status": "completed", "checks_failed_blocking": 3})
        with patch.object(temporalio.workflow, "execute_child_workflow", new=child):
            blocking = await workflow._run_staged_audit(_inputs(), "job-1", _materialize_result("gate"), "staged_1")

        assert blocking == 3
        assert child.await_args is not None
        payload = child.await_args.args[1]
        assert payload["saved_query_ids"] == ["sq-1"]
        assert payload["staged_queryable_folder"] == "staged_1"

    async def test_fails_open_when_the_suite_errors(self):
        # An audit that cannot run is an operational problem, not a data verdict: the publish
        # must proceed rather than wedging every refresh on a broken check pipeline.
        workflow = MaterializeViewWorkflow()
        with (
            patch.object(
                temporalio.workflow, "execute_child_workflow", new=AsyncMock(side_effect=RuntimeError("timeout"))
            ),
            patch.object(temporalio.workflow, "logger"),
            patch(f"{WORKFLOW_MODULE}.capture_exception"),
        ):
            blocking = await workflow._run_staged_audit(_inputs(), "job-1", _materialize_result("gate"), "staged_1")

        assert blocking == 0


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
