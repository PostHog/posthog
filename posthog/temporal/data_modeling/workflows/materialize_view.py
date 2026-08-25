import json
import uuid
import asyncio
import datetime as dt
import dataclasses

from django.conf import settings

import temporalio.common
import temporalio.workflow
import temporalio.exceptions
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.data_modeling.activities import (
    ClearCDPStagingInputs,
    CreateDataModelingJobInputs,
    DuckgresShadowInputs,
    DuckgresShadowResult,
    FailMaterializationInputs,
    MaterializeViewInputs,
    MaterializeViewResult,
    PrepareQueryableTableInputs,
    PrepareQueryableTableResult,
    PublishQueryableTableInputs,
    QualityBlockMaterializationInputs,
    StageQueryableFilesResult,
    SucceedMaterializationInputs,
    SucceedMaterializationResult,
    check_duckgres_shadow_enabled_activity,
    clear_cdp_staging_activity,
    create_data_modeling_job_activity,
    fail_materialization_activity,
    materialize_view_activity,
    materialize_view_duckgres_activity,
    prepare_queryable_table_activity,
    publish_queryable_table_activity,
    quality_block_materialization_activity,
    stage_queryable_files_activity,
    succeed_materialization_activity,
)
from posthog.temporal.data_modeling.activities.enrich_view_semantics import EnrichViewSemanticsInputs
from posthog.temporal.data_modeling.metrics import (
    get_clickhouse_materialization_duration_metric,
    get_duckgres_shadow_duration_metric,
    get_duckgres_shadow_finished_metric,
    get_duckgres_shadow_row_count_match_metric,
    get_duckgres_shadow_rows_materialized_metric,
    get_duckgres_shadow_storage_delta_mib_metric,
    get_duckgres_shadow_storage_mib_metric,
    get_node_duration_metric,
    get_node_finished_metric,
    get_node_rows_materialized_metric,
    get_node_storage_delta_mib_metric,
    get_node_total_storage_mib_metric,
)
from posthog.temporal.data_modeling.workflows.enrich_view_semantics import EnrichViewSemanticsWorkflow
from posthog.temporal.utils import CDPProducerWorkflowInputs

from products.customer_analytics.backend.facade.temporal_contracts import (
    DispatchAccountPropertySyncInput,
    StageAccountPropertySyncInput,
)
from products.data_modeling.backend.facade.models import DataModelingJobEngine
from products.data_quality.backend.facade.contracts import (
    CHECK_SUITE_WORKFLOW_NAME,
    QUALITY_AUDIT_GATE,
    QUALITY_AUDIT_SKIP,
    QUALITY_AUDIT_WARN,
    QualityAuditMode,
    is_quality_audit_mode,
)
from products.data_quality.backend.facade.enums import SuiteRunTrigger
from products.warehouse_sources.backend.facade.hooks import (
    MATERIALIZED_VIEW_SOURCE_TYPE,
    PersonPropertySyncActivityInputs,
)

# Covers every command the data quality feature adds here: the stage/audit/publish trio and the
# warn-mode suite child.
QUALITY_AUDIT_PATCH = "data-quality-audit-2026-08"
ACCOUNT_PROPERTY_S3_SYNC_PATCH = "account-property-s3-sync-2026-08"
ACCOUNT_PROPERTY_STAGING_WORKFLOW_PATCH = "account-property-staging-workflow-2026-08"

# Covers the CDP producer child and the staging-cleanup activity. Both are new commands, so a
# history recorded before this deploy has to keep taking the branch that issues neither.
CDP_VIEW_TRIGGER_PATCH = "cdp-data-warehouse-view-trigger-2026-08"

# these indicate problems with the query or data, not transient issues
NON_RETRYABLE_ERRORS = [
    "CHQueryErrorMemoryLimitExceeded",
    "CannotCoerceColumnException",
    "InvalidNodeTypeException",
    "NodeNotFoundException",
    "EmptyHogQLResponseColumnsError",
]


def _is_cancellation(error: BaseException) -> bool:
    """The SDK never re-delivers a cancel, so a handler that swallows one keeps issuing commands."""
    if isinstance(error, temporalio.exceptions.CancelledError | asyncio.CancelledError):
        return True
    return isinstance(
        error, temporalio.exceptions.ActivityError | temporalio.exceptions.ChildWorkflowError
    ) and isinstance(error.cause, temporalio.exceptions.CancelledError)


@dataclasses.dataclass
class MaterializeViewWorkflowInputs:
    """Inputs for the MaterializeViewWorkflow.

    Attributes:
        team_id: The team ID that owns the node.
        dag_id: The DAG the node belongs to.
        node_id: The UUID of the Node to materialize.
    """

    team_id: int
    dag_id: str
    node_id: str
    duckgres_only: bool = False
    dangerously_execute_raw_sql: bool = False

    @property
    def properties_to_log(self) -> dict:
        return {
            "team_id": self.team_id,
            "dag_id": self.dag_id,
            "node_id": self.node_id,
        }


@dataclasses.dataclass(frozen=False)
class MaterializeViewWorkflowResult:
    """Result from the MaterializeViewWorkflow.

    Attributes:
        job_id: The ID of the DataModelingJob created for this run.
        node_id: The ID of the node that was materialized.
        rows_materialized: The number of rows written to the delta table.
        duration_seconds: The total duration of the workflow in seconds.
        quality_blocking_failures: Error-severity check failures that blocked the publish. None
            means no gated audit ran.
        quality_audited: Whether a check suite covered this run, so the DAG's post-run sweep must
            not run one again.
    """

    job_id: str
    node_id: str
    rows_materialized: int
    duration_seconds: float
    quality_blocking_failures: int | None = None
    quality_audited: bool = False


@temporalio.workflow.defn(name="data-modeling-materialize-view")
class MaterializeViewWorkflow(PostHogWorkflow):
    """Temporal workflow to materialize a single view.

    This workflow handles the complete materialization of a single view/materialized view:
    1. Creates a job record to track progress
    2. Executes the HogQL query and writes results to a delta lake table
    3. Copies the data to DuckLake (if enabled)
    4. Updates the node and job with completion status

    This workflow is designed to be called directly for ad hoc materialization of a single view
    (i.e. a user clicks 'materialize now' or something to that effect), or as a child workflow
    from the DAG orchestrator workflow
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> MaterializeViewWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return MaterializeViewWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: MaterializeViewWorkflowInputs) -> MaterializeViewWorkflowResult:
        temporalio.workflow.logger.info("Starting MaterializeViewWorkflow", extra=inputs.properties_to_log)
        start_time = temporalio.workflow.now()
        parent_info = temporalio.workflow.info().parent
        parent_workflow_id = parent_info.workflow_id if parent_info else None
        job_id = None
        duckgres_job_id = None

        # check whether duckgres shadow is enabled before creating the job
        duckgres_enabled = await temporalio.workflow.execute_activity(
            check_duckgres_shadow_enabled_activity,
            inputs.team_id,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                maximum_attempts=3,
            ),
        )

        duckgres_shadow_handle = None
        if duckgres_enabled or inputs.duckgres_only:
            duckgres_job_id = await temporalio.workflow.execute_activity(
                create_data_modeling_job_activity,
                CreateDataModelingJobInputs(
                    team_id=inputs.team_id,
                    node_id=inputs.node_id,
                    dag_id=inputs.dag_id,
                    engine=DataModelingJobEngine.DUCKGRES,
                    parent_workflow_id=parent_workflow_id,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=3,
                ),
            )
            # fire-and-forget: start duckgres shadow materialization in parallel
            duckgres_shadow_handle = temporalio.workflow.start_activity(
                materialize_view_duckgres_activity,
                DuckgresShadowInputs(
                    team_id=inputs.team_id,
                    node_id=inputs.node_id,
                    dag_id=inputs.dag_id,
                    job_id=duckgres_job_id,
                    dangerously_execute_raw_sql=inputs.dangerously_execute_raw_sql,
                ),
                start_to_close_timeout=dt.timedelta(minutes=20),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=3 if inputs.duckgres_only else 1,
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=5),
                ),
            )

        if not inputs.duckgres_only:
            job_id = await temporalio.workflow.execute_activity(
                create_data_modeling_job_activity,
                CreateDataModelingJobInputs(
                    team_id=inputs.team_id,
                    node_id=inputs.node_id,
                    dag_id=inputs.dag_id,
                    parent_workflow_id=parent_workflow_id,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=3,
                ),
            )
            materialize_result: MaterializeViewResult | None = None
            try:
                materialize_result = await temporalio.workflow.execute_activity(
                    materialize_view_activity,
                    MaterializeViewInputs(
                        team_id=inputs.team_id,
                        node_id=inputs.node_id,
                        dag_id=inputs.dag_id,
                        job_id=job_id,
                    ),
                    # clickhouse timeout is 10mins so start to close is that plus a bit of margin
                    start_to_close_timeout=dt.timedelta(minutes=20),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=temporalio.common.RetryPolicy(
                        maximum_attempts=3,
                        initial_interval=dt.timedelta(seconds=10),
                        maximum_interval=dt.timedelta(minutes=5),
                        non_retryable_error_types=NON_RETRYABLE_ERRORS,
                    ),
                    cancellation_type=temporalio.workflow.ActivityCancellationType.TRY_CANCEL,
                )

                # prepare files for querying and create DataWarehouseTable.
                # materialize_view_activity guarantees file_uris is non-empty even for
                # zero-row results — it falls back to _write_empty_parquet_for_zero_rows
                # so prepare_s3_files_for_querying has something to list.
                # Reading the mode as skip when the marker is absent keeps every command this
                # feature adds out of a history that predates it. A rolling deploy can hand an old
                # workflow worker a result from new activity code, and the SDK drops the fields the
                # old dataclass lacks, so the mode alone cannot say who wrote the history.
                quality_audit = (
                    self._audit_mode(materialize_result, inputs)
                    if temporalio.workflow.patched(QUALITY_AUDIT_PATCH)
                    else QUALITY_AUDIT_SKIP
                )
                staged_verdict: int | None = None
                prepare_inputs = PrepareQueryableTableInputs(
                    team_id=inputs.team_id,
                    job_id=job_id,
                    saved_query_id=materialize_result.saved_query_id,
                    table_uri=materialize_result.table_uri,
                    file_uris=materialize_result.file_uris,
                    row_count=materialize_result.row_count,
                    incremental=materialize_result.incremental,
                )
                if quality_audit == QUALITY_AUDIT_GATE:
                    stage_result: StageQueryableFilesResult = await temporalio.workflow.execute_activity(
                        stage_queryable_files_activity,
                        prepare_inputs,
                        start_to_close_timeout=dt.timedelta(minutes=5),
                        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
                    )
                    staged_verdict = await self._staged_audit_verdict(
                        inputs, job_id, materialize_result, stage_result.staged_folder_path
                    )
                    if staged_verdict:
                        await temporalio.workflow.execute_activity(
                            quality_block_materialization_activity,
                            QualityBlockMaterializationInputs(
                                team_id=inputs.team_id,
                                node_id=inputs.node_id,
                                dag_id=inputs.dag_id,
                                job_id=job_id,
                                blocking_failures=staged_verdict,
                            ),
                            start_to_close_timeout=dt.timedelta(minutes=5),
                            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
                        )
                        get_node_finished_metric("quality_blocked").add(1)
                        if temporalio.workflow.patched(CDP_VIEW_TRIGGER_PATCH):
                            await self._discard_staged_cdp_rows(inputs, job_id, materialize_result)
                        end_time = temporalio.workflow.now()
                        blocked_duration_seconds = (end_time - start_time).total_seconds()
                        if duckgres_shadow_handle is not None:
                            await self._collect_shadow_comparison(
                                duckgres_shadow_handle,
                                duckgres_job_id,
                                materialize_result.row_count,
                                blocked_duration_seconds,
                                inputs,
                            )
                        return MaterializeViewWorkflowResult(
                            job_id=job_id,
                            node_id=inputs.node_id,
                            rows_materialized=materialize_result.row_count,
                            duration_seconds=blocked_duration_seconds,
                            quality_blocking_failures=staged_verdict,
                            quality_audited=True,
                        )
                    storage_result: PrepareQueryableTableResult = await temporalio.workflow.execute_activity(
                        publish_queryable_table_activity,
                        PublishQueryableTableInputs(
                            **dataclasses.asdict(prepare_inputs),
                            staged_folder_path=stage_result.staged_folder_path,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=5),
                        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
                    )
                else:
                    storage_result = await temporalio.workflow.execute_activity(
                        prepare_queryable_table_activity,
                        prepare_inputs,
                        start_to_close_timeout=dt.timedelta(minutes=5),
                        retry_policy=temporalio.common.RetryPolicy(
                            maximum_attempts=3,
                        ),
                    )
                # handle success
                end_time = temporalio.workflow.now()
                duration_seconds = (end_time - start_time).total_seconds()
                succeed_result = await temporalio.workflow.execute_activity(
                    succeed_materialization_activity,
                    SucceedMaterializationInputs(
                        team_id=inputs.team_id,
                        node_id=inputs.node_id,
                        dag_id=inputs.dag_id,
                        job_id=job_id,
                        row_count=materialize_result.row_count,
                        duration_seconds=duration_seconds,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=temporalio.common.RetryPolicy(
                        maximum_attempts=3,
                    ),
                )

                # Draft/refresh the view's semantic descriptions once its definition or columns changed
                # (including the first materialization). Fire-and-forget on the metadata queue so LLM work
                # never contends with materialization slots or blocks this workflow. `succeed_result` is
                # None for in-flight runs on the pre-deploy activity version — treat that as "not needed".
                await self._maybe_enrich_view_semantics(inputs, succeed_result)

                if temporalio.workflow.patched(CDP_VIEW_TRIGGER_PATCH):
                    await self._maybe_produce_cdp_rows(inputs, job_id, materialize_result)

                quality_audited = staged_verdict is not None
                if quality_audit == QUALITY_AUDIT_WARN:
                    quality_audited = await self._start_suite_on_published_data(inputs, job_id, materialize_result)

                # Upsert this view's columns onto person/group properties for any warehouse property
                # that reads it. Fire-and-forget on the metadata queue, like enrichment above.
                await self._maybe_sync_person_properties(inputs, materialize_result, job_id)

                # New executions start the isolated staging child. A history that recorded the old
                # inline dispatch under ACCOUNT_PROPERTY_S3_SYNC_PATCH must keep emitting that
                # command on replay, so keep the old path in the else branch.
                if temporalio.workflow.patched(ACCOUNT_PROPERTY_STAGING_WORKFLOW_PATCH):
                    await self._maybe_stage_account_properties(inputs, materialize_result, job_id)
                elif temporalio.workflow.patched(ACCOUNT_PROPERTY_S3_SYNC_PATCH):
                    await self._replay_account_property_dispatch(inputs, materialize_result, job_id)

                # after the main workflow succeeds, collect shadow stats for comparison
                if duckgres_shadow_handle is not None:
                    await self._collect_shadow_comparison(
                        duckgres_shadow_handle,
                        duckgres_job_id,
                        materialize_result.row_count,
                        duration_seconds,
                        inputs,
                    )

                temporalio.workflow.logger.info(
                    "MaterializeViewWorkflow completed successfully",
                    extra={
                        "rows_materialized": materialize_result.row_count,
                        "duration_seconds": duration_seconds,
                        **inputs.properties_to_log,
                    },
                )

                # node-level metrics
                get_node_finished_metric("completed").add(1)
                get_node_duration_metric().record(duration_seconds)
                get_node_rows_materialized_metric().record(materialize_result.row_count)
                if storage_result.storage_delta_mib is not None and storage_result.storage_delta_mib >= 0:
                    get_node_storage_delta_mib_metric().record(storage_result.storage_delta_mib)
                if storage_result.total_storage_mib is not None:
                    get_node_total_storage_mib_metric().record(storage_result.total_storage_mib)

                return MaterializeViewWorkflowResult(
                    job_id=job_id,
                    node_id=inputs.node_id,
                    rows_materialized=materialize_result.row_count,
                    duration_seconds=duration_seconds,
                    quality_blocking_failures=staged_verdict,
                    quality_audited=quality_audited,
                )
            except Exception as e:
                # handle failure
                cancelled = _is_cancellation(e)
                if cancelled:
                    error_message = "Workflow was cancelled"
                elif isinstance(e, temporalio.exceptions.ActivityError):
                    error_message = str(e.cause) if e.cause else str(e)
                else:
                    capture_exception(e)
                    error_message = str(e)
                temporalio.workflow.logger.error(
                    f"MaterializeViewWorkflow failed: {error_message}",
                    extra=inputs.properties_to_log,
                )
                # A failure after the activity returned (publish, succeed) leaves that run's staged
                # rows behind. The activity cleans up after its own failures itself.
                if materialize_result is not None and temporalio.workflow.patched(CDP_VIEW_TRIGGER_PATCH):
                    await self._discard_staged_cdp_rows(inputs, job_id, materialize_result)
                try:
                    await temporalio.workflow.execute_activity(
                        fail_materialization_activity,
                        FailMaterializationInputs(
                            team_id=inputs.team_id,
                            node_id=inputs.node_id,
                            dag_id=inputs.dag_id,
                            job_id=job_id,
                            error=error_message,
                            cancelled=cancelled,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=5),
                        retry_policy=temporalio.common.RetryPolicy(
                            maximum_attempts=3,
                        ),
                    )
                except Exception as fail_err:
                    temporalio.workflow.logger.error(
                        f"Failed to mark job as failed: {str(fail_err)}",
                        extra=inputs.properties_to_log,
                    )
                get_node_finished_metric("cancelled" if cancelled else "failed").add(1)
                raise

        # await the duckgres shadow activity so the parent workflow's concurrency
        # semaphore isn't released until the query finishes on duckgres
        result = None
        if duckgres_shadow_handle is not None:
            try:
                result = await duckgres_shadow_handle
            except Exception as shadow_err:
                await self._finalize_orphaned_duckgres_job(duckgres_job_id, inputs, str(shadow_err))
                temporalio.workflow.logger.warning(
                    f"Duckgres shadow activity failed (duckgres_only): {str(shadow_err)}",
                    extra=inputs.properties_to_log,
                )
                capture_exception(shadow_err)
        # fallback to duckgres job if no clickhouse job was run
        if job_id is None:
            if duckgres_job_id is None:
                raise temporalio.exceptions.ApplicationError("No data modeling job was created")
            job_id = duckgres_job_id
        return MaterializeViewWorkflowResult(
            job_id=job_id,
            node_id=inputs.node_id,
            rows_materialized=result.row_count if result else 0,
            duration_seconds=result.duration_seconds if result else 0,
        )

    async def _staged_audit_verdict(
        self,
        inputs: MaterializeViewWorkflowInputs,
        job_id: str,
        materialize_result: MaterializeViewResult,
        staged_folder_path: str,
    ) -> int | None:
        """The blocking-failure count, or None when the audit reached no verdict.

        None still publishes, because a broken check pipeline is not a verdict on the data, and it
        leaves the node to the DAG's sweep so the checks get another chance. Cancellation is not
        such a case, so it propagates rather than publishing unaudited data.
        """
        try:
            result = await temporalio.workflow.execute_child_workflow(
                CHECK_SUITE_WORKFLOW_NAME,
                {
                    "team_id": inputs.team_id,
                    "trigger": SuiteRunTrigger.MATERIALIZATION.value,
                    "saved_query_ids": [materialize_result.saved_query_id],
                    "data_modeling_job_id": job_id,
                    "staged_queryable_folder": staged_folder_path,
                },
                id=f"data-quality-gate-{job_id}",
                task_queue=settings.DATA_MODELING_TASK_QUEUE,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(minutes=30),
            )
        except Exception as e:
            if _is_cancellation(e):
                raise
            capture_exception(e)
            temporalio.workflow.logger.warning(
                "Staged data quality audit did not complete; publishing without a verdict",
                extra={"error": str(e), **inputs.properties_to_log},
            )
            return None
        if isinstance(result, dict):
            return int(result.get("checks_failed_blocking") or 0)
        return None

    async def _start_suite_on_published_data(
        self,
        inputs: MaterializeViewWorkflowInputs,
        job_id: str,
        materialize_result: MaterializeViewResult,
    ) -> bool:
        """False sends the node back to the DAG's sweep, which is where a failed start gets covered."""
        try:
            await temporalio.workflow.start_child_workflow(
                CHECK_SUITE_WORKFLOW_NAME,
                {
                    "team_id": inputs.team_id,
                    "trigger": SuiteRunTrigger.MATERIALIZATION.value,
                    "saved_query_ids": [materialize_result.saved_query_id],
                    "data_modeling_job_id": job_id,
                },
                id=f"data-quality-materialization-{job_id}",
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(hours=1),
            )
        except WorkflowAlreadyStartedError:
            temporalio.workflow.logger.info(
                "Data quality checks already running for this job, skipping",
                extra=inputs.properties_to_log,
            )
            return True
        except Exception as e:
            capture_exception(e)
            temporalio.workflow.logger.warning(
                "Could not start the data quality check suite",
                extra={"error": str(e), **inputs.properties_to_log},
            )
            return False
        return True

    def _audit_mode(
        self, materialize_result: MaterializeViewResult, inputs: MaterializeViewWorkflowInputs
    ) -> QualityAuditMode:
        """A mode this version does not know reads as ``skip``, the behavior that predates the gate."""
        mode = materialize_result.quality_audit
        if is_quality_audit_mode(mode):
            return mode
        temporalio.workflow.logger.warning(
            f"Unknown data quality audit mode {mode!r}, publishing without a gate",
            extra=inputs.properties_to_log,
        )
        return QUALITY_AUDIT_SKIP

    async def _maybe_sync_person_properties(
        self,
        inputs: MaterializeViewWorkflowInputs,
        materialize_result: MaterializeViewResult,
        job_id: str,
    ) -> None:
        """Fire the person-property sync child when this run staged rows for a warehouse property.

        Same isolation as enrichment above: ABANDON so it never blocks or fails this workflow, and
        every error swallowed. Keyed per job rather than per view, because each run stages its rows
        under a job-scoped S3 prefix that only its own child consumes — a per-view id would coalesce
        a concurrent run's child and silently drop that run's staged rows.

        Gated on ``person_property_sync_enabled``, a defaulted field on the materialize activity's
        result, so an in-flight run recorded before this existed decodes it as False and never runs
        this command during replay.
        """
        if not materialize_result.person_property_sync_enabled:
            return
        try:
            await temporalio.workflow.start_child_workflow(
                "sync-warehouse-person-properties",
                PersonPropertySyncActivityInputs(
                    team_id=inputs.team_id,
                    schema_id=None,
                    source_id=None,
                    job_id=job_id,
                    source_type=MATERIALIZED_VIEW_SOURCE_TYPE,
                    schema_name=materialize_result.node_name,
                    last_synced_at=None,
                    saved_query_id=uuid.UUID(materialize_result.saved_query_id),
                ),
                id=f"sync-warehouse-person-properties-{job_id}",
                id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                execution_timeout=dt.timedelta(hours=6),
            )
        except WorkflowAlreadyStartedError:
            temporalio.workflow.logger.info(
                "Person-property sync already running for this job, skipping",
                extra={"job_id": job_id},
            )
        except Exception as e:
            capture_exception(e)
            temporalio.workflow.logger.warning(
                "Failed to start person-property sync",
                extra={"job_id": job_id, "error": str(e)},
            )

    async def _replay_account_property_dispatch(
        self,
        inputs: MaterializeViewWorkflowInputs,
        materialize_result: MaterializeViewResult,
        job_id: str,
    ) -> None:
        if not materialize_result.account_property_sync_enabled:
            return
        await temporalio.workflow.execute_activity(
            "dispatch-warehouse-account-property-sync",
            DispatchAccountPropertySyncInput(
                team_id=inputs.team_id,
                saved_query_id=materialize_result.saved_query_id,
                job_id=job_id,
            ),
            task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=5),
        )

    async def _maybe_stage_account_properties(
        self,
        inputs: MaterializeViewWorkflowInputs,
        materialize_result: MaterializeViewResult,
        job_id: str,
    ) -> None:
        if not materialize_result.account_property_sync_enabled or materialize_result.delta_version is None:
            return
        try:
            await temporalio.workflow.start_child_workflow(
                "stage-warehouse-account-properties",
                StageAccountPropertySyncInput(
                    team_id=inputs.team_id,
                    saved_query_id=materialize_result.saved_query_id,
                    job_id=job_id,
                    table_uri=materialize_result.table_uri,
                    delta_version=materialize_result.delta_version,
                ),
                id=f"stage-warehouse-account-properties-{job_id}",
                id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                execution_timeout=dt.timedelta(hours=24),
            )
        except WorkflowAlreadyStartedError:
            temporalio.workflow.logger.info(
                "Account-property staging already running for this job, skipping",
                extra={"job_id": job_id},
            )
        except Exception as error:
            capture_exception(error)
            temporalio.workflow.logger.warning(
                "Failed to start account-property staging",
                extra={"job_id": job_id, "error": str(error)},
            )

    async def _maybe_produce_cdp_rows(
        self,
        inputs: MaterializeViewWorkflowInputs,
        job_id: str,
        materialize_result: MaterializeViewResult,
    ) -> None:
        """Hand this run's rows to the CDP producer so subscribed destinations and workflows run.

        Started only after the queryable publish, so a destination that queries the view back sees
        the rows it was told about. Best effort and fully isolated: ABANDON so it never blocks this
        workflow, and every error is swallowed — a trigger that misses a run must not fail the
        materialization behind it.
        """
        if not materialize_result.should_trigger_cdp_producer:
            return

        try:
            await temporalio.workflow.start_child_workflow(
                workflow="dwh-cdp-producer-job",
                arg=dataclasses.asdict(
                    CDPProducerWorkflowInputs(
                        team_id=inputs.team_id,
                        job_id=job_id,
                        saved_query_id=materialize_result.saved_query_id,
                    )
                ),
                id=f"dwh-cdp-producer-job-{job_id}",
                task_queue=str(settings.DATA_WAREHOUSE_CDP_PRODUCER_TASK_QUEUE),
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=3,
                    non_retryable_error_types=["NondeterminismError"],
                ),
            )
        except WorkflowAlreadyStartedError:
            # Already running against this job's staged rows, so they are still wanted.
            temporalio.workflow.logger.info(
                "CDP producer job already running, skipping",
                extra={"job_id": job_id},
            )
        except Exception as e:
            capture_exception(e)
            temporalio.workflow.logger.warning(
                "Failed to start the CDP producer job",
                extra={"job_id": job_id, "error": str(e)},
            )
            # Nothing will ever read this job's staged rows now, and its prefix is keyed on the job,
            # so no later run's own clear would reach them.
            await self._discard_staged_cdp_rows(inputs, job_id, materialize_result)

    async def _discard_staged_cdp_rows(
        self,
        inputs: MaterializeViewWorkflowInputs,
        job_id: str,
        materialize_result: MaterializeViewResult,
    ) -> None:
        """Drop rows staged by a run that then never published.

        The staging prefix is keyed on the job, so no later run's own clear will ever reach it.
        """
        if not materialize_result.should_trigger_cdp_producer:
            return

        try:
            await temporalio.workflow.execute_activity(
                clear_cdp_staging_activity,
                ClearCDPStagingInputs(
                    team_id=inputs.team_id,
                    saved_query_id=materialize_result.saved_query_id,
                    job_id=job_id,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
            )
        except Exception as e:
            capture_exception(e)
            temporalio.workflow.logger.warning(
                "Failed to clear staged CDP rows",
                extra={"job_id": job_id, "error": str(e)},
            )

    async def _maybe_enrich_view_semantics(
        self,
        inputs: MaterializeViewWorkflowInputs,
        succeed_result: SucceedMaterializationResult | None,
    ) -> None:
        """Fire the semantic-enrichment child when the just-materialized view's descriptions are stale.

        Best-effort and fully isolated: keyed per saved query so a concurrent run gets
        WorkflowAlreadyStartedError (swallowed), ABANDON so it never blocks or fails this workflow, and any
        other error is swallowed so enrichment can never break a materialization. A None result comes from
        an in-flight run on the pre-deploy activity version and is treated as "not needed".
        """
        if succeed_result is None or not succeed_result.enrichment_needed or not succeed_result.saved_query_id:
            return
        saved_query_id = succeed_result.saved_query_id
        try:
            await temporalio.workflow.start_child_workflow(
                EnrichViewSemanticsWorkflow.run,
                EnrichViewSemanticsInputs(team_id=inputs.team_id, saved_query_id=saved_query_id),
                id=f"enrich-view-semantics-{saved_query_id}",
                id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                execution_timeout=dt.timedelta(minutes=30),
            )
        except WorkflowAlreadyStartedError:
            temporalio.workflow.logger.info(
                "View semantic enrichment already running, skipping",
                extra={"saved_query_id": saved_query_id},
            )
        except Exception as e:
            capture_exception(e)
            temporalio.workflow.logger.warning(
                "Failed to start view semantic enrichment",
                extra={"saved_query_id": saved_query_id, "error": str(e)},
            )

    async def _collect_shadow_comparison(
        self,
        shadow_handle: temporalio.workflow.ActivityHandle[DuckgresShadowResult],
        duckgres_job_id: str | None,
        clickhouse_row_count: int,
        clickhouse_duration_seconds: float,
        inputs: MaterializeViewWorkflowInputs,
    ) -> None:
        """Await the duckgres shadow activity and emit comparison metrics.

        The activity itself is responsible for updating its job to a terminal state.
        This is best-effort — any failure is swallowed so it never affects the workflow result.
        """
        try:
            shadow_result: DuckgresShadowResult = await shadow_handle

            row_count_matched = clickhouse_row_count == shadow_result.row_count
            status = "completed" if shadow_result.error is None else "failed"

            # prometheus metrics
            get_duckgres_shadow_finished_metric(status).add(1)
            get_clickhouse_materialization_duration_metric().record(clickhouse_duration_seconds)
            if shadow_result.error is None:
                get_duckgres_shadow_duration_metric().record(shadow_result.duration_seconds)
                get_duckgres_shadow_rows_materialized_metric().record(shadow_result.row_count)
                get_duckgres_shadow_row_count_match_metric(row_count_matched).add(1)
                if shadow_result.file_size_bytes > 0:
                    get_duckgres_shadow_storage_mib_metric().record(shadow_result.file_size_bytes / (1024 * 1024))
                    if shadow_result.file_size_delta_bytes >= 0:
                        get_duckgres_shadow_storage_delta_mib_metric().record(
                            shadow_result.file_size_delta_bytes / (1024 * 1024)
                        )

            # structured log for detailed comparison
            temporalio.workflow.logger.info(
                "duckgres_shadow_comparison",
                extra={
                    "clickhouse_rows": clickhouse_row_count,
                    "clickhouse_duration_seconds": round(clickhouse_duration_seconds, 2),
                    "duckgres_rows": shadow_result.row_count,
                    "duckgres_duration_seconds": round(shadow_result.duration_seconds, 2),
                    "duckgres_schema": shadow_result.schema_name,
                    "duckgres_table": shadow_result.table_name,
                    "duckgres_error": shadow_result.error,
                    "row_count_match": row_count_matched,
                    **inputs.properties_to_log,
                },
            )
        except Exception as shadow_err:
            get_duckgres_shadow_finished_metric("error").add(1)
            # the activity died before it could self-finalize its job — back it up here
            await self._finalize_orphaned_duckgres_job(duckgres_job_id, inputs, str(shadow_err))
            temporalio.workflow.logger.warning(
                f"Duckgres shadow comparison failed: {str(shadow_err)}",
                extra=inputs.properties_to_log,
            )
            capture_exception(shadow_err)

    async def _finalize_orphaned_duckgres_job(
        self,
        duckgres_job_id: str | None,
        inputs: MaterializeViewWorkflowInputs,
        error: str,
    ) -> None:
        """Mark a duckgres shadow job FAILED when its activity died before self-finalizing.

        The shadow activity finalizes its own job on the happy path and on caught errors, but a
        timeout, worker loss, or a raise before its try block leaves the job stuck in RUNNING. The
        workflow is the only place guaranteed to observe the activity's death, so it backstops
        finalization here. Idempotent: fail_materialization_activity skips already-terminal jobs.
        """
        if duckgres_job_id is None:
            return
        try:
            await temporalio.workflow.execute_activity(
                fail_materialization_activity,
                FailMaterializationInputs(
                    team_id=inputs.team_id,
                    node_id=inputs.node_id,
                    dag_id=inputs.dag_id,
                    job_id=duckgres_job_id,
                    error=f"Duckgres shadow activity did not finalize: {error}",
                    update_node=False,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
            )
        except Exception as fail_err:
            temporalio.workflow.logger.warning(
                f"Failed to finalize orphaned duckgres job: {str(fail_err)}",
                extra=inputs.properties_to_log,
            )
