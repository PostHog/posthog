import datetime as dt
import dataclasses
from collections.abc import Callable
from contextlib import ExitStack

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import temporalio.workflow
from temporalio.exceptions import CancelledError, ChildWorkflowError, WorkflowAlreadyStartedError

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
    ACCOUNT_PROPERTY_S3_SYNC_PATCH,
    ACCOUNT_PROPERTY_STAGING_WORKFLOW_PATCH,
    MaterializeViewWorkflow,
    MaterializeViewWorkflowInputs,
)

from products.customer_analytics.backend.facade.temporal_contracts import StageAccountPropertySyncInput
from products.data_quality.backend.facade.contracts import CHECK_SUITE_WORKFLOW_NAME, QualityAuditMode
from products.warehouse_sources.backend.facade.hooks import PersonPropertySyncActivityInputs

pytestmark = pytest.mark.asyncio

WORKFLOW_MODULE = "posthog.temporal.data_modeling.workflows.materialize_view"


def _inputs() -> MaterializeViewWorkflowInputs:
    return MaterializeViewWorkflowInputs(team_id=7, dag_id="dag-1", node_id="node-1")


def _materialize_result(quality_audit: QualityAuditMode) -> MaterializeViewResult:
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
    async def _run(
        self,
        activity_results: list,
        child_result: dict | Exception,
        *,
        patched: bool | Callable[[str], bool] = True,
        shadow_handle: AsyncMock | None = None,
        start_child: AsyncMock | None = None,
    ) -> tuple:
        execute_activity = AsyncMock(side_effect=activity_results)
        child = (
            AsyncMock(side_effect=child_result)
            if isinstance(child_result, Exception)
            else AsyncMock(return_value=child_result)
        )
        info = MagicMock()
        info.parent = None
        with ExitStack() as stack:
            stack.enter_context(patch.object(temporalio.workflow, "execute_activity", new=execute_activity))
            stack.enter_context(patch.object(temporalio.workflow, "execute_child_workflow", new=child))
            stack.enter_context(
                patch.object(temporalio.workflow, "start_child_workflow", new=start_child or AsyncMock())
            )
            patched_mock = (
                patch.object(temporalio.workflow, "patched", side_effect=patched)
                if callable(patched)
                else patch.object(temporalio.workflow, "patched", return_value=patched)
            )
            stack.enter_context(patched_mock)
            stack.enter_context(patch.object(temporalio.workflow, "info", return_value=info))
            stack.enter_context(patch.object(temporalio.workflow, "now", return_value=dt.datetime(2026, 8, 1)))
            stack.enter_context(patch.object(temporalio.workflow, "logger"))
            stack.enter_context(patch(f"{WORKFLOW_MODULE}.capture_exception"))
            if shadow_handle is not None:
                stack.enter_context(patch.object(temporalio.workflow, "start_activity", return_value=shadow_handle))
            for metric in (
                "get_node_finished_metric",
                "get_node_duration_metric",
                "get_node_rows_materialized_metric",
                "get_node_storage_delta_mib_metric",
                "get_node_total_storage_mib_metric",
                "get_duckgres_shadow_finished_metric",
                "get_clickhouse_materialization_duration_metric",
                "get_duckgres_shadow_duration_metric",
                "get_duckgres_shadow_rows_materialized_metric",
                "get_duckgres_shadow_row_count_match_metric",
                "get_duckgres_shadow_storage_mib_metric",
                "get_duckgres_shadow_storage_delta_mib_metric",
            ):
                stack.enter_context(patch(f"{WORKFLOW_MODULE}.{metric}"))
            result = await MaterializeViewWorkflow().run(_inputs())
        return result, execute_activity

    async def test_blocking_failures_stop_the_publish(self):
        activity_results = [
            False,  # duckgres shadow check
            "job-1",  # create job
            _materialize_result("gate"),
            StageQueryableFilesResult(staged_folder_path="staged_1"),
            None,  # quality_block_materialization
        ]

        result, execute_activity = await self._run(activity_results, {"checks_failed_blocking": 2})

        assert result.quality_blocking_failures == 2
        assert result.quality_audited is True
        started = [call.args[0].__name__ for call in execute_activity.await_args_list]
        assert started[-2:] == ["stage_queryable_files_activity", "quality_block_materialization_activity"]
        assert "publish_queryable_table_activity" not in started
        assert "succeed_materialization_activity" not in started

    async def test_account_staging_starts_an_isolated_child_workflow(self):
        materialize_result = dataclasses.replace(
            _materialize_result("skip"),
            account_property_sync_enabled=True,
            delta_version=5,
        )
        activity_results = [
            False,
            "job-1",
            materialize_result,
            PrepareQueryableTableResult(storage_delta_mib=None, total_storage_mib=None),
            None,
            None,
        ]
        start_child = AsyncMock()

        await self._run(activity_results, {}, start_child=start_child)

        staging_call = next(
            call for call in start_child.await_args_list if call.args[0] == "stage-warehouse-account-properties"
        )
        assert isinstance(staging_call.args[1], StageAccountPropertySyncInput)
        assert staging_call.args[1].job_id == "job-1"
        assert staging_call.args[1].delta_version == 5
        assert staging_call.kwargs["parent_close_policy"] == temporalio.workflow.ParentClosePolicy.ABANDON

    async def test_a_legacy_history_replays_the_inline_dispatch_command(self):
        # A history recorded under ACCOUNT_PROPERTY_S3_SYNC_PATCH holds the old dispatch activity
        # command and no delta_version. Replaying it with only that marker present must re-emit the
        # dispatch command, not the staging child, or the execution fails as nondeterministic.
        materialize_result = dataclasses.replace(
            _materialize_result("skip"),
            account_property_sync_enabled=True,
        )
        activity_results = [
            False,
            "job-1",
            materialize_result,
            PrepareQueryableTableResult(storage_delta_mib=None, total_storage_mib=None),
            None,
            None,
        ]
        start_child = AsyncMock()

        _, execute_activity = await self._run(
            activity_results,
            {},
            patched=lambda change_id: change_id == ACCOUNT_PROPERTY_S3_SYNC_PATCH,
            start_child=start_child,
        )

        assert any(
            call.args[0] == "dispatch-warehouse-account-property-sync" for call in execute_activity.await_args_list
        )
        assert not [
            call for call in start_child.await_args_list if call.args[0] == "stage-warehouse-account-properties"
        ]

    async def test_the_isolated_staging_child_wins_when_both_markers_are_present(self):
        materialize_result = dataclasses.replace(
            _materialize_result("skip"),
            account_property_sync_enabled=True,
            delta_version=5,
        )
        activity_results = [
            False,
            "job-1",
            materialize_result,
            PrepareQueryableTableResult(storage_delta_mib=None, total_storage_mib=None),
            None,
        ]
        start_child = AsyncMock()

        _, execute_activity = await self._run(
            activity_results,
            {},
            patched=lambda change_id: (
                change_id in (ACCOUNT_PROPERTY_STAGING_WORKFLOW_PATCH, ACCOUNT_PROPERTY_S3_SYNC_PATCH)
            ),
            start_child=start_child,
        )

        assert any(call.args[0] == "stage-warehouse-account-properties" for call in start_child.await_args_list)
        assert not any(
            call.args[0] == "dispatch-warehouse-account-property-sync" for call in execute_activity.await_args_list
        )

    async def test_a_passing_audit_publishes_and_succeeds(self):
        activity_results = [
            False,
            "job-1",
            _materialize_result("gate"),
            StageQueryableFilesResult(staged_folder_path="staged_1"),
            PrepareQueryableTableResult(storage_delta_mib=None, total_storage_mib=None),  # publish
            None,  # succeed (pre-deploy shape is fine, enrichment skipped)
        ]

        result, execute_activity = await self._run(activity_results, {"checks_failed_blocking": 0})

        assert result.quality_blocking_failures == 0
        started = [call.args[0].__name__ for call in execute_activity.await_args_list]
        assert "publish_queryable_table_activity" in started
        assert "succeed_materialization_activity" in started

    @pytest.mark.parametrize("mode", ["gate", "warn"])
    async def test_a_history_without_the_patch_marker_adds_no_command(self, mode):
        # A rolling deploy pairs an old workflow worker with a new activity worker, and the SDK
        # drops the fields the old dataclass lacks. So a mode can reach a history that recorded
        # only the prepare command, and replaying it here has to emit exactly that.
        activity_results = [
            False,
            "job-1",
            _materialize_result(mode),
            PrepareQueryableTableResult(storage_delta_mib=None, total_storage_mib=None),  # prepare
            None,  # succeed
        ]
        start_child = AsyncMock()

        result, execute_activity = await self._run(
            activity_results, {"checks_failed_blocking": 2}, patched=False, start_child=start_child
        )

        started = [call.args[0].__name__ for call in execute_activity.await_args_list]
        assert "prepare_queryable_table_activity" in started
        assert "stage_queryable_files_activity" not in started
        assert "quality_block_materialization_activity" not in started
        start_child.assert_not_awaited()
        assert result.quality_blocking_failures is None
        assert result.quality_audited is False

    async def test_an_audit_that_reached_no_verdict_leaves_the_node_to_the_sweep(self):
        # Returning zero here would publish and also claim the node was audited, so the DAG's
        # fallback sweep would skip the one node whose checks never ran.
        activity_results = [
            False,
            "job-1",
            _materialize_result("gate"),
            StageQueryableFilesResult(staged_folder_path="staged_1"),
            PrepareQueryableTableResult(storage_delta_mib=None, total_storage_mib=None),  # publish
            None,  # succeed
        ]

        result, execute_activity = await self._run(activity_results, RuntimeError("suite died"))

        started = [call.args[0].__name__ for call in execute_activity.await_args_list]
        assert "publish_queryable_table_activity" in started
        assert result.quality_blocking_failures is None
        assert result.quality_audited is False

    @pytest.mark.parametrize(
        "start_child,expected_audited",
        [
            (AsyncMock(), True),
            (AsyncMock(side_effect=WorkflowAlreadyStartedError("id", "type")), True),
            (AsyncMock(side_effect=RuntimeError("task queue is gone")), False),
        ],
    )
    async def test_a_warn_suite_that_never_started_sends_the_node_back_to_the_sweep(
        self, start_child, expected_audited
    ) -> None:
        activity_results = [
            False,
            "job-1",
            _materialize_result("warn"),
            PrepareQueryableTableResult(storage_delta_mib=None, total_storage_mib=None),  # prepare
            None,  # succeed
        ]

        result, _ = await self._run(activity_results, {}, start_child=start_child)

        assert result.quality_audited is expected_audited
        assert result.quality_blocking_failures is None

    async def test_a_blocked_publish_still_settles_the_duckgres_shadow(self):
        # The blocked branch returns early. Leaving the shadow activity unawaited holds the parent
        # DAG's concurrency slot and orphans the shadow job.
        shadow_handle = AsyncMock()
        shadow_handle.__await__ = lambda self=None: iter([])
        activity_results = [
            True,  # duckgres shadow enabled
            "duckgres-job-1",  # create duckgres job
            "job-1",  # create clickhouse job
            _materialize_result("gate"),
            StageQueryableFilesResult(staged_folder_path="staged_1"),
            None,  # quality_block_materialization
        ]

        with patch.object(MaterializeViewWorkflow, "_collect_shadow_comparison", new=AsyncMock()) as collect:
            result, _ = await self._run(activity_results, {"checks_failed_blocking": 1}, shadow_handle=shadow_handle)

        assert result.quality_blocking_failures == 1
        collect.assert_awaited_once()


def _cancelled_child_error() -> ChildWorkflowError:
    error = ChildWorkflowError(
        "child cancelled",
        namespace="default",
        workflow_id="data-quality-gate-job-1",
        run_id="run-1",
        workflow_type=CHECK_SUITE_WORKFLOW_NAME,
        initiated_event_id=1,
        started_event_id=2,
        retry_state=None,
    )
    error.__cause__ = CancelledError("cancelled")
    return error


class TestStagedAudit:
    async def _staged_verdict(self, workflow: MaterializeViewWorkflow) -> int | None:
        return await workflow._staged_audit_verdict(_inputs(), "job-1", _materialize_result("gate"), "staged_1")

    async def test_reads_the_blocking_count_from_the_suite_result(self):
        child = AsyncMock(return_value={"suite_run_id": "s-1", "status": "completed", "checks_failed_blocking": 3})
        with patch.object(temporalio.workflow, "execute_child_workflow", new=child):
            verdict = await self._staged_verdict(MaterializeViewWorkflow())

        assert verdict == 3
        assert child.await_args is not None
        payload = child.await_args.args[1]
        assert payload["saved_query_ids"] == ["sq-1"]
        assert payload["staged_queryable_folder"] == "staged_1"

    async def test_a_suite_that_errors_reaches_no_verdict(self):
        with (
            patch.object(
                temporalio.workflow, "execute_child_workflow", new=AsyncMock(side_effect=RuntimeError("timeout"))
            ),
            patch.object(temporalio.workflow, "logger"),
            patch(f"{WORKFLOW_MODULE}.capture_exception"),
        ):
            verdict = await self._staged_verdict(MaterializeViewWorkflow())

        assert verdict is None

    @pytest.mark.parametrize(
        "cancellation",
        [CancelledError("cancelled"), _cancelled_child_error()],
    )
    async def test_cancellation_is_not_a_verdict_to_fail_open_on(self, cancellation):
        with (
            patch.object(temporalio.workflow, "execute_child_workflow", new=AsyncMock(side_effect=cancellation)),
            patch.object(temporalio.workflow, "logger"),
            patch(f"{WORKFLOW_MODULE}.capture_exception"),
        ):
            with pytest.raises(type(cancellation)):
                await self._staged_verdict(MaterializeViewWorkflow())


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


class TestMaybeStageAccountProperties:
    async def test_starts_an_abandoned_staging_child(self):
        workflow = MaterializeViewWorkflow()
        result = dataclasses.replace(
            _materialize_result("skip"),
            account_property_sync_enabled=True,
            delta_version=5,
        )
        start_child = AsyncMock()
        with patch.object(temporalio.workflow, "start_child_workflow", new=start_child):
            await workflow._maybe_stage_account_properties(_inputs(), result, "job-123")

        start_child.assert_awaited_once()
        assert start_child.await_args is not None
        workflow_name, payload = start_child.await_args.args
        assert workflow_name == "stage-warehouse-account-properties"
        assert isinstance(payload, StageAccountPropertySyncInput)
        assert payload.job_id == "job-123"
        assert payload.delta_version == 5
        assert start_child.await_args.kwargs["parent_close_policy"] == temporalio.workflow.ParentClosePolicy.ABANDON

    async def test_staging_start_failure_does_not_fail_materialization(self):
        workflow = MaterializeViewWorkflow()
        result = dataclasses.replace(
            _materialize_result("skip"),
            account_property_sync_enabled=True,
            delta_version=5,
        )
        start_child = AsyncMock(side_effect=PermissionError("access denied"))
        with (
            patch.object(temporalio.workflow, "start_child_workflow", new=start_child),
            patch.object(temporalio.workflow, "logger", new=MagicMock()),
            patch("posthog.temporal.data_modeling.workflows.materialize_view.capture_exception"),
        ):
            await workflow._maybe_stage_account_properties(_inputs(), result, "job-123")

        start_child.assert_awaited_once()

    async def test_no_staging_when_no_account_sources_are_enabled(self):
        workflow = MaterializeViewWorkflow()
        start_child = AsyncMock()
        with patch.object(temporalio.workflow, "start_child_workflow", new=start_child):
            await workflow._maybe_stage_account_properties(_inputs(), _materialize_result("skip"), "job-123")
        start_child.assert_not_awaited()


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


def _person_sync_result(**overrides) -> MaterializeViewResult:
    kwargs: dict = {
        "node_id": "node-1",
        "node_name": "enriched_users",
        "row_count": 3,
        "table_uri": "s3://bucket/team_7_model_abc/modeling/enriched_users",
        "file_uris": ["s3://bucket/f.parquet"],
        "saved_query_id": "0198f2b1-0000-7000-8000-000000000001",
    }
    kwargs.update(overrides)
    return MaterializeViewResult(**kwargs)


class TestMaybeSyncPersonProperties:
    async def test_starts_child_with_the_view_binding_when_rows_were_staged(self):
        workflow = MaterializeViewWorkflow()
        result = _person_sync_result(person_property_sync_enabled=True)
        with patch.object(temporalio.workflow, "start_child_workflow", new=AsyncMock()) as start_child:
            await workflow._maybe_sync_person_properties(_inputs(), result, "job-123")

        start_child.assert_awaited_once()
        assert start_child.await_args is not None
        name, payload = start_child.await_args.args
        assert name == "sync-warehouse-person-properties"
        assert isinstance(payload, PersonPropertySyncActivityInputs)
        # The child reads the rows this run staged, so it has to name the view, not a schema.
        assert payload.schema_id is None
        assert str(payload.saved_query_id) == result.saved_query_id
        assert payload.binding.kind == "saved_query"
        assert payload.job_id == "job-123"
        # Keyed per job: a per-view id would coalesce a concurrent run's child and drop its staged rows.
        assert start_child.await_args.kwargs["id"] == "sync-warehouse-person-properties-job-123"

    async def test_no_child_when_nothing_was_staged(self):
        # The flag defaults to False, so a run recorded before this existed decodes it as False and
        # never fires this command during replay — which is what keeps in-flight runs deterministic.
        workflow = MaterializeViewWorkflow()
        assert _person_sync_result().person_property_sync_enabled is False
        with patch.object(temporalio.workflow, "start_child_workflow", new=AsyncMock()) as start_child:
            await workflow._maybe_sync_person_properties(_inputs(), _person_sync_result(), "job-123")
        start_child.assert_not_awaited()

    @pytest.mark.parametrize(
        "error",
        [WorkflowAlreadyStartedError("sync-warehouse-person-properties-job-123", "type"), RuntimeError("boom")],
    )
    async def test_start_failures_never_fail_the_materialization(self, error):
        workflow = MaterializeViewWorkflow()
        result = _person_sync_result(person_property_sync_enabled=True)
        with (
            patch.object(temporalio.workflow, "start_child_workflow", new=AsyncMock(side_effect=error)),
            patch.object(temporalio.workflow, "logger"),
            patch(f"{WORKFLOW_MODULE}.capture_exception"),
        ):
            await workflow._maybe_sync_person_properties(_inputs(), result, "job-123")


class TestCDPProducerHandoff(TestQualityGateBranching):
    """When the workflow hands a run's staged rows to the CDP producer, and when it throws them away."""

    @staticmethod
    def _result(*, should_trigger: bool, quality_audit: QualityAuditMode = "skip") -> MaterializeViewResult:
        result = _materialize_result(quality_audit)
        return dataclasses.replace(result, should_trigger_cdp_producer=should_trigger)

    async def test_the_producer_starts_after_a_successful_publish(self):
        start_child = AsyncMock()
        activity_results = [
            False,
            "job-1",
            self._result(should_trigger=True),
            PrepareQueryableTableResult(storage_delta_mib=None, total_storage_mib=None),
            SucceedMaterializationResult(enrichment_needed=False, saved_query_id="sq-1"),
        ]

        await self._run(activity_results, {"checks_failed_blocking": 0}, start_child=start_child)

        started = [call.kwargs.get("workflow") or call.args[0] for call in start_child.await_args_list]
        assert "dwh-cdp-producer-job" in started

    async def test_no_producer_starts_when_nothing_subscribes(self):
        start_child = AsyncMock()
        activity_results = [
            False,
            "job-1",
            self._result(should_trigger=False),
            PrepareQueryableTableResult(storage_delta_mib=None, total_storage_mib=None),
            SucceedMaterializationResult(enrichment_needed=False, saved_query_id="sq-1"),
        ]

        await self._run(activity_results, {"checks_failed_blocking": 0}, start_child=start_child)

        started = [call.kwargs.get("workflow") or call.args[0] for call in start_child.await_args_list]
        assert "dwh-cdp-producer-job" not in started

    async def test_a_producer_that_fails_to_start_clears_the_staged_rows(self):
        # Nothing will read them now, and the prefix is keyed on this job, so no later run's own
        # clear reaches them.
        start_child = AsyncMock(side_effect=RuntimeError("task queue is gone"))
        activity_results = [
            False,
            "job-1",
            self._result(should_trigger=True),
            PrepareQueryableTableResult(storage_delta_mib=None, total_storage_mib=None),
            SucceedMaterializationResult(enrichment_needed=False, saved_query_id="sq-1"),
            None,  # clear_cdp_staging
        ]

        _, execute_activity = await self._run(activity_results, {"checks_failed_blocking": 0}, start_child=start_child)

        started = [call.args[0].__name__ for call in execute_activity.await_args_list]
        assert "clear_cdp_staging_activity" in started

    async def test_a_quality_blocked_run_clears_its_staged_rows_instead_of_producing(self):
        # The rows were never published, and the prefix is keyed on this job, so no later run's own
        # clear will ever reach them.
        start_child = AsyncMock()
        activity_results = [
            False,
            "job-1",
            self._result(should_trigger=True, quality_audit="gate"),
            StageQueryableFilesResult(staged_folder_path="staged_1"),
            None,  # quality_block_materialization
            None,  # clear_cdp_staging
        ]

        _, execute_activity = await self._run(activity_results, {"checks_failed_blocking": 2}, start_child=start_child)

        started = [call.args[0].__name__ for call in execute_activity.await_args_list]
        assert "clear_cdp_staging_activity" in started
        assert "dwh-cdp-producer-job" not in [
            call.kwargs.get("workflow") or call.args[0] for call in start_child.await_args_list
        ]
