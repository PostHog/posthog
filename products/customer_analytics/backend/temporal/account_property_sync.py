from __future__ import annotations

import json
import time
import asyncio

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from products.customer_analytics.backend.facade.temporal_contracts import (
    AccountPropertySyncCoordinatorInput,
    AccountPropertySyncInput,
    AccountPropertySyncWork,
    DispatchAccountPropertySyncInput,
    FinalizeAccountPropertySyncRunsInput,
    StageAccountPropertySyncInput,
)

with workflow.unsafe.imports_passed_through():
    from datetime import timedelta
    from uuid import UUID

    from django.conf import settings

    import structlog
    from prometheus_client import Counter, Histogram

    from posthog.models.scoping.manager import resolve_effective_team_id
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.client import async_connect

    from products.customer_analytics.backend.logic.account_property_coordination import (
        AccountPropertySyncSuperseded,
        account_property_coordination_enabled,
        begin_account_property_sync_attempt,
        finish_account_property_sync,
        get_next_account_property_sync,
        guard_account_property_sync_attempt,
        request_account_property_sync,
    )
    from products.customer_analytics.backend.logic.account_property_runs import (
        AccountPropertySyncRunContext,
        AccountPropertySyncRunOutcome,
        finalize_account_property_sync_runs,
        finish_account_property_sync_runs,
        start_account_property_sync_runs,
        update_account_property_sync_runs_phase,
    )
    from products.customer_analytics.backend.logic.account_property_sync import (
        AccountPropertySourceValueError,
        AccountPropertySyncSegment,
        _mark_completed_and_maybe_cleanup,
        run_account_property_segment_sync,
    )
    from products.customer_analytics.backend.logic.custom_property_sync import sync_custom_property_values
    from products.customer_analytics.backend.models.custom_property_sync_run import SyncPhase, SyncSegment, SyncStatus
    from products.warehouse_sources.backend.facade.hooks import saved_query_binding
    from products.warehouse_sources.backend.facade.temporal import AccountPropertyRowSink

logger = structlog.get_logger(__name__)

ACCOUNT_PROPERTY_STAGING_WORKFLOW_NAME = "stage-warehouse-account-properties"
ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME = "sync-warehouse-account-properties"
ACCOUNT_PROPERTY_COORDINATOR_WORKFLOW_NAME = "coordinate-account-properties"
ACCOUNT_PROPERTY_RUN_HISTORY_PATCH = "account-property-run-history-2026-08"
ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS = 5
ACCOUNT_PROPERTY_COORDINATOR_HISTORY_BATCH = 100

_SYNC_FAILED_ERROR = "Couldn't update accounts. Run the source view again. If it keeps failing, contact support."

_STAGING_FAILED_ERROR = (
    "Couldn't prepare warehouse rows. Run the source view again. If it keeps failing, contact support."
)
_DISPATCH_FAILED_ERROR = (
    "Couldn't start account updates. Run the source view again. If it keeps failing, contact support."
)

ACCOUNT_PROPERTY_SYNC_TOTAL = Counter(
    "warehouse_account_property_sync_total",
    "Account-property sync activity attempts by segment and outcome",
    labelnames=["team_id", "segment", "outcome"],
)

ACCOUNT_PROPERTY_SYNC_DURATION_SECONDS = Histogram(
    "warehouse_account_property_sync_duration_seconds",
    "Duration of one account-property segment sync",
    labelnames=["segment"],
    buckets=(0.5, 1.0, 2.5, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0),
)


@activity.defn(name="start-warehouse-account-property-runs")
async def start_warehouse_account_property_runs_activity(input: DispatchAccountPropertySyncInput) -> None:
    activity_info = activity.info()
    await database_sync_to_async(start_account_property_sync_runs)(
        AccountPropertySyncRunContext(
            team_id=input.team_id,
            saved_query_id=input.saved_query_id,
            job_id=input.job_id,
        ),
        workflow_id=activity_info.workflow_id,
        workflow_run_id=activity_info.workflow_run_id,
    )


@activity.defn(name="finalize-warehouse-account-property-runs")
async def finalize_warehouse_account_property_runs_activity(input: FinalizeAccountPropertySyncRunsInput) -> None:
    await database_sync_to_async(finalize_account_property_sync_runs)(
        AccountPropertySyncRunContext(
            team_id=input.team_id,
            saved_query_id=input.saved_query_id,
            job_id=input.job_id,
        ),
        status=SyncStatus(input.status),
        phase=SyncPhase(input.phase),
        error=input.error,
    )


@activity.defn(name="stage-warehouse-account-property-files")
async def stage_warehouse_account_property_files_activity(input: StageAccountPropertySyncInput) -> bool:
    activity_info = activity.info()
    await database_sync_to_async(update_account_property_sync_runs_phase)(
        AccountPropertySyncRunContext(
            team_id=input.team_id,
            saved_query_id=input.saved_query_id,
            job_id=input.job_id,
        ),
        phase=SyncPhase.STAGING,
        workflow_id=activity_info.workflow_id,
        workflow_run_id=activity_info.workflow_run_id,
        attempt=activity_info.attempt,
    )
    log = logger.bind(
        team_id=input.team_id,
        saved_query_id=input.saved_query_id,
        job_id=input.job_id,
        delta_version=input.delta_version,
    )
    sink = AccountPropertyRowSink(
        team_id=input.team_id,
        binding=saved_query_binding(input.saved_query_id),
        job_id=input.job_id,
        logger=log,
    )
    try:
        async with Heartbeater():
            staged = await sink.stage_delta_snapshot(input.table_uri, input.delta_version)
    except Exception as error:
        log.exception("Account-property staging failed")
        capture_exception(error)
        raise
    if staged:
        log.info("Account-property staging completed")
    else:
        log.info("Account-property staging skipped because no enabled sources remain")
    return staged


@activity.defn(name="dispatch-warehouse-account-property-sync")
async def dispatch_warehouse_account_property_sync_activity(input: DispatchAccountPropertySyncInput) -> None:
    activity_info = activity.info()
    await database_sync_to_async(update_account_property_sync_runs_phase)(
        AccountPropertySyncRunContext(
            team_id=input.team_id,
            saved_query_id=input.saved_query_id,
            job_id=input.job_id,
        ),
        phase=SyncPhase.DISPATCHING,
        workflow_id=activity_info.workflow_id,
        workflow_run_id=activity_info.workflow_run_id,
        attempt=activity_info.attempt,
    )
    if account_property_coordination_enabled():
        await register_staged_account_property_sync(input)
        return

    client = await async_connect()
    for segment in ("tracked", "ignored"):
        workflow_id = f"sync-warehouse-account-properties-{input.job_id}-{segment}"
        try:
            await client.start_workflow(
                ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME,
                AccountPropertySyncInput(
                    team_id=input.team_id,
                    saved_query_id=input.saved_query_id,
                    job_id=input.job_id,
                    segment=segment,
                ),
                id=workflow_id,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
                execution_timeout=timedelta(hours=24),
            )
        except WorkflowAlreadyStartedError:
            logger.info(
                "Account-property segment sync already running",
                team_id=input.team_id,
                job_id=input.job_id,
                segment=segment,
            )


@activity.defn
async def sync_warehouse_account_properties_activity(input: AccountPropertySyncInput) -> dict[str, int]:
    if input.request_id is None and account_property_coordination_enabled():
        await register_staged_account_property_sync(
            DispatchAccountPropertySyncInput(
                team_id=input.team_id, saved_query_id=input.saved_query_id, job_id=input.job_id
            )
        )
        return {"delegated": 1}

    segment = AccountPropertySyncSegment(input.segment)
    activity_info = activity.info()
    await database_sync_to_async(update_account_property_sync_runs_phase)(
        AccountPropertySyncRunContext(
            team_id=input.team_id,
            saved_query_id=input.saved_query_id,
            job_id=input.job_id,
        ),
        phase=SyncPhase.SYNCING,
        workflow_id=activity_info.workflow_id,
        workflow_run_id=activity_info.workflow_run_id,
        attempt=activity_info.attempt,
        segment=segment,
    )
    log = logger.bind(
        team_id=input.team_id,
        saved_query_id=input.saved_query_id,
        job_id=input.job_id,
        segment=segment.value,
    )
    started = time.monotonic()
    try:
        async with Heartbeater():
            sync_read = None
            if input.request_id is not None:
                sync_read = await database_sync_to_async(begin_account_property_sync_attempt)(
                    team_id=input.team_id,
                    saved_query_id=input.saved_query_id,
                    request_id=input.request_id,
                    segment=segment.value,
                )
            result = await run_account_property_segment_sync(
                team_id=input.team_id,
                binding=saved_query_binding(input.saved_query_id),
                job_id=input.job_id,
                segment=segment,
                final_attempt=activity_info.attempt >= ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS,
                sync_read=sync_read,
            )
    except AccountPropertySyncSuperseded:
        return {"superseded": 1}
    except AccountPropertySourceValueError as error:
        ACCOUNT_PROPERTY_SYNC_TOTAL.labels(team_id=str(input.team_id), segment=segment.value, outcome="failed").inc()
        log.warning("Account-property segment sync rejected invalid source values", error=str(error))
        raise ApplicationError(str(error), non_retryable=True) from error
    except Exception as error:
        ACCOUNT_PROPERTY_SYNC_TOTAL.labels(team_id=str(input.team_id), segment=segment.value, outcome="failed").inc()
        log.exception("Account-property segment sync failed")
        capture_exception(error)
        raise

    ACCOUNT_PROPERTY_SYNC_TOTAL.labels(team_id=str(input.team_id), segment=segment.value, outcome="completed").inc()
    ACCOUNT_PROPERTY_SYNC_DURATION_SECONDS.labels(segment=segment.value).observe(time.monotonic() - started)
    log.info("Account-property segment sync completed", **result)
    return result


async def wake_account_property_sync_coordinator(input: AccountPropertySyncCoordinatorInput) -> None:
    team_id = await database_sync_to_async(resolve_effective_team_id)(input.team_id)
    input = AccountPropertySyncCoordinatorInput(team_id=team_id, saved_query_id=input.saved_query_id)
    client = await async_connect()
    await client.start_workflow(
        ACCOUNT_PROPERTY_COORDINATOR_WORKFLOW_NAME,
        input,
        id=f"coordinate-account-properties-{input.team_id}-{input.saved_query_id}",
        task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        start_signal="wake",
    )


async def register_staged_account_property_sync(input: DispatchAccountPropertySyncInput) -> None:
    await database_sync_to_async(request_account_property_sync)(
        team_id=input.team_id, saved_query_id=input.saved_query_id, job_id=input.job_id
    )
    await wake_account_property_sync_coordinator(
        AccountPropertySyncCoordinatorInput(team_id=input.team_id, saved_query_id=input.saved_query_id)
    )


@activity.defn(name="get-next-account-property-sync")
async def get_next_account_property_sync_activity(
    input: AccountPropertySyncCoordinatorInput,
) -> AccountPropertySyncWork | None:
    return await database_sync_to_async(get_next_account_property_sync)(
        team_id=input.team_id, saved_query_id=input.saved_query_id
    )


@activity.defn(name="finish-account-property-sync")
async def finish_account_property_sync_activity(input: AccountPropertySyncWork, error: str | None) -> None:
    if error is not None:
        capture_exception(ApplicationError(error))
        await database_sync_to_async(finalize_account_property_sync_runs)(
            AccountPropertySyncRunContext(
                team_id=input.team_id, saved_query_id=input.saved_query_id, job_id=input.job_id
            ),
            status=SyncStatus.FAILED,
            phase=SyncPhase.SYNCING,
            error=_SYNC_FAILED_ERROR,
        )
    await database_sync_to_async(finish_account_property_sync)(
        team_id=input.team_id, saved_query_id=input.saved_query_id, request_id=input.request_id, error=error
    )
    if error is None and input.kind == "staged":
        try:
            for segment in AccountPropertySyncSegment:
                await _mark_completed_and_maybe_cleanup(
                    input.team_id, saved_query_binding(input.saved_query_id), input.job_id, segment
                )
        except Exception as cleanup_error:
            logger.exception("Account-property staged file cleanup failed", job_id=input.job_id)
            capture_exception(cleanup_error)


def _sync_live_account_properties(input: AccountPropertySyncWork) -> dict[str, int]:
    sync_read = begin_account_property_sync_attempt(
        team_id=input.team_id,
        saved_query_id=input.saved_query_id,
        request_id=input.request_id,
        segment="live",
    )
    context = AccountPropertySyncRunContext(
        team_id=input.team_id, saved_query_id=input.saved_query_id, job_id=input.job_id
    )
    info = activity.info()
    with guard_account_property_sync_attempt(sync_read):
        start_account_property_sync_runs(context, workflow_id=info.workflow_id, workflow_run_id=info.workflow_run_id)
        update_account_property_sync_runs_phase(
            context,
            phase=SyncPhase.SYNCING,
            workflow_id=info.workflow_id,
            workflow_run_id=info.workflow_run_id,
            attempt=info.attempt,
        )
    result = sync_custom_property_values(
        team_id=input.team_id, saved_query_id=input.saved_query_id, sync_read=sync_read
    )
    counts = {
        "written": result.written,
        "unmatched_keys": result.unmatched_keys,
        "accounts_total": result.accounts_total,
        "rows_fetched": result.rows_fetched,
        "source_errors": len(result.source_errors),
        "deferred": result.deferred,
    }
    if result.deferred:
        return counts
    with guard_account_property_sync_attempt(sync_read, exclusive=True):
        source_mapping_keys = getattr(result, "source_mapping_keys", None)
        if not result.view_found:
            raise ApplicationError("The account-property source view is no longer available.", non_retryable=True)

        # The live reader exposes aggregate counts, not per-source counts. Keep source failures
        # visible without attributing the aggregate to every source and doubling its counts.
        outcomes = [
            AccountPropertySyncRunOutcome(
                source_id=UUID(source_id), rows_read=0, changed=0, matched=0, written=0, error=error
            )
            for source_id, error in result.source_errors.items()
        ]
        for segment in SyncSegment:
            finish_account_property_sync_runs(context, segment, outcomes, source_mapping_keys=source_mapping_keys)
        finalize_account_property_sync_runs(
            context, status=SyncStatus.COMPLETED, phase=SyncPhase.COMPLETED, source_mapping_keys=source_mapping_keys
        )
    if result.source_errors:
        raise ApplicationError(
            f"{len(result.source_errors)} account-property source(s) contained invalid values", non_retryable=True
        )
    return counts


@activity.defn(name="sync-live-account-properties")
async def sync_live_account_properties_activity(input: AccountPropertySyncWork) -> dict[str, int]:
    try:
        async with Heartbeater():
            return await database_sync_to_async(_sync_live_account_properties)(input)
    except AccountPropertySyncSuperseded:
        return {"superseded": 1}
    except Exception as error:
        logger.exception("Live account-property sync failed", request_id=input.request_id, team_id=input.team_id)
        capture_exception(error)
        raise


@workflow.defn(name=ACCOUNT_PROPERTY_COORDINATOR_WORKFLOW_NAME)
class AccountPropertySyncCoordinatorWorkflow(PostHogWorkflow):
    def __init__(self) -> None:
        self._wake_requested = False

    @staticmethod
    def parse_inputs(inputs: list[str]) -> AccountPropertySyncCoordinatorInput:
        return AccountPropertySyncCoordinatorInput(**json.loads(inputs[0]))

    @workflow.signal(name="wake")
    def wake(self) -> None:
        self._wake_requested = True

    async def _sync_work(self, work: AccountPropertySyncWork) -> str | None:
        pending = ["live"] if work.kind == "live" else ["tracked", "ignored"]
        errors: list[str] = []
        while pending:
            activities = []
            for segment in pending:
                activity_input = (
                    work
                    if segment == "live"
                    else AccountPropertySyncInput(
                        team_id=work.team_id,
                        saved_query_id=work.saved_query_id,
                        job_id=work.job_id,
                        segment=segment,
                        request_id=work.request_id,
                    )
                )
                activities.append(
                    workflow.execute_activity(
                        "sync-live-account-properties"
                        if segment == "live"
                        else "sync_warehouse_account_properties_activity",
                        activity_input,
                        result_type=dict[str, int],
                        start_to_close_timeout=timedelta(hours=6),
                        heartbeat_timeout=timedelta(minutes=5),
                        retry_policy=RetryPolicy(
                            maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS,
                            initial_interval=timedelta(seconds=30),
                        ),
                    )
                )
            # A failed segment must not release the next bulk while its sibling still writes.
            results = await asyncio.gather(*activities, return_exceptions=True)
            deferred = []
            for segment, result in zip(pending, results):
                if isinstance(result, BaseException):
                    if not isinstance(result, Exception):
                        raise result
                    cause: BaseException = result
                    while cause.__cause__ is not None:
                        cause = cause.__cause__
                    errors.append(f"{segment}: {cause}")
                elif result.get("deferred", 0) > 0:
                    deferred.append(segment)
            pending = deferred
            if pending:
                await workflow.sleep(timedelta(seconds=30))
        return "; ".join(errors) or None

    @workflow.run
    async def run(self, input: AccountPropertySyncCoordinatorInput) -> None:
        processed = 0
        while True:
            self._wake_requested = False
            work = await workflow.execute_activity(
                get_next_account_property_sync_activity,
                input,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS),
            )
            if work is None:
                await workflow.wait_condition(workflow.all_handlers_finished)
                if self._wake_requested:
                    continue
                return
            error = await self._sync_work(work)
            await workflow.execute_activity(
                finish_account_property_sync_activity,
                args=[work, error],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS),
            )
            processed += 1
            if (
                processed >= ACCOUNT_PROPERTY_COORDINATOR_HISTORY_BATCH
                or workflow.info().is_continue_as_new_suggested()
            ):
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(input)


@workflow.defn(name=ACCOUNT_PROPERTY_STAGING_WORKFLOW_NAME)
class StageWarehouseAccountPropertiesWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> StageAccountPropertySyncInput:
        return StageAccountPropertySyncInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, input: StageAccountPropertySyncInput) -> None:
        run_history_enabled = workflow.patched(ACCOUNT_PROPERTY_RUN_HISTORY_PATCH)
        lifecycle_input = DispatchAccountPropertySyncInput(
            team_id=input.team_id,
            saved_query_id=input.saved_query_id,
            job_id=input.job_id,
        )
        if run_history_enabled:
            await workflow.execute_activity(
                start_warehouse_account_property_runs_activity,
                lifecycle_input,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS),
            )

        try:
            staged = await workflow.execute_activity(
                stage_warehouse_account_property_files_activity,
                input,
                start_to_close_timeout=timedelta(hours=6),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS,
                    initial_interval=timedelta(seconds=30),
                ),
            )
        except Exception:
            if run_history_enabled:
                await workflow.execute_activity(
                    finalize_warehouse_account_property_runs_activity,
                    FinalizeAccountPropertySyncRunsInput(
                        team_id=input.team_id,
                        saved_query_id=input.saved_query_id,
                        job_id=input.job_id,
                        status=SyncStatus.FAILED.value,
                        phase=SyncPhase.STAGING.value,
                        error=_STAGING_FAILED_ERROR,
                    ),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS),
                )
            raise

        if not staged:
            if run_history_enabled:
                await workflow.execute_activity(
                    finalize_warehouse_account_property_runs_activity,
                    FinalizeAccountPropertySyncRunsInput(
                        team_id=input.team_id,
                        saved_query_id=input.saved_query_id,
                        job_id=input.job_id,
                        status=SyncStatus.COMPLETED.value,
                        phase=SyncPhase.COMPLETED.value,
                    ),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS),
                )
            return

        try:
            await workflow.execute_activity(
                dispatch_warehouse_account_property_sync_activity,
                lifecycle_input,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS),
            )
        except Exception:
            if run_history_enabled:
                await workflow.execute_activity(
                    finalize_warehouse_account_property_runs_activity,
                    FinalizeAccountPropertySyncRunsInput(
                        team_id=input.team_id,
                        saved_query_id=input.saved_query_id,
                        job_id=input.job_id,
                        status=SyncStatus.FAILED.value,
                        phase=SyncPhase.DISPATCHING.value,
                        error=_DISPATCH_FAILED_ERROR,
                    ),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS),
                )
            raise


@workflow.defn(name=ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME)
class SyncWarehouseAccountPropertiesWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> AccountPropertySyncInput:
        return AccountPropertySyncInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, input: AccountPropertySyncInput) -> None:
        await workflow.execute_activity(
            sync_warehouse_account_properties_activity,
            input,
            start_to_close_timeout=timedelta(hours=6),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS,
                initial_interval=timedelta(seconds=30),
            ),
        )


ACCOUNT_PROPERTY_SYNC_WORKFLOWS = [
    StageWarehouseAccountPropertiesWorkflow,
    SyncWarehouseAccountPropertiesWorkflow,
    AccountPropertySyncCoordinatorWorkflow,
]
ACCOUNT_PROPERTY_SYNC_ACTIVITIES = [
    start_warehouse_account_property_runs_activity,
    finalize_warehouse_account_property_runs_activity,
    stage_warehouse_account_property_files_activity,
    dispatch_warehouse_account_property_sync_activity,
    sync_warehouse_account_properties_activity,
    get_next_account_property_sync_activity,
    sync_live_account_properties_activity,
    finish_account_property_sync_activity,
]
