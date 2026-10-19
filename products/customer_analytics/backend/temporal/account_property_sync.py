from __future__ import annotations

import json
import time
import asyncio
from typing import Literal

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ApplicationError, WorkflowAlreadyStartedError, is_cancelled_exception

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from products.customer_analytics.backend.facade.temporal_contracts import (
    AccountPropertySegmentTelemetryInput,
    AccountPropertySyncInput,
    DispatchAccountPropertySyncInput,
    FinalizeAccountPropertySyncRunsInput,
    StageAccountPropertySyncInput,
)

with workflow.unsafe.imports_passed_through():
    from datetime import timedelta

    from django.conf import settings

    import structlog
    from prometheus_client import Counter, Histogram

    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.client import async_connect

    from products.customer_analytics.backend.logic.account_property_runs import (
        AccountPropertySyncRunContext,
        finalize_account_property_sync_runs,
        start_account_property_sync_runs,
        update_account_property_sync_runs_phase,
    )
    from products.customer_analytics.backend.logic.account_property_sync import (
        AccountPropertySourceValueError,
        AccountPropertySyncSegment,
        run_account_property_segment_sync,
    )
    from products.customer_analytics.backend.logic.account_property_sync_monitoring import (
        capture_account_property_sync_event,
    )
    from products.customer_analytics.backend.models.custom_property_sync_run import SyncPhase, SyncStatus
    from products.warehouse_sources.backend.facade.hooks import saved_query_binding
    from products.warehouse_sources.backend.facade.temporal import AccountPropertyRowSink

logger = structlog.get_logger(__name__)

ACCOUNT_PROPERTY_STAGING_WORKFLOW_NAME = "stage-warehouse-account-properties"
ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME = "sync-warehouse-account-properties"
ACCOUNT_PROPERTY_RUN_HISTORY_PATCH = "account-property-run-history-2026-08"
ACCOUNT_PROPERTY_SEGMENT_TELEMETRY_PATCH = "account-property-segment-telemetry-2026-10"
ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS = 5

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

_SyncPath = Literal["legacy", "fanout"]
_TerminalStatus = Literal["completed", "failed", "cancelled"]


def _failure_type(error: BaseException) -> str:
    cause = error.cause if isinstance(error, ActivityError) and error.cause is not None else error
    if isinstance(cause, ApplicationError) and cause.type:
        return cause.type
    return type(cause).__name__


@frozen
class _AttemptTelemetry:
    team_id: int
    saved_query_id: str
    job_id: str
    segment: str
    path: _SyncPath
    source_id: str | None
    attempt: int
    workflow_id: str | None
    workflow_run_id: str | None
    started_at: float

    @classmethod
    def start(
        cls,
        *,
        team_id: int,
        saved_query_id: str,
        job_id: str,
        segment: str,
        path: _SyncPath,
        source_id: str | None = None,
    ) -> _AttemptTelemetry:
        info = activity.info()
        telemetry = cls(
            team_id=team_id,
            saved_query_id=saved_query_id,
            job_id=job_id,
            segment=segment,
            path=path,
            source_id=source_id,
            attempt=info.attempt,
            workflow_id=info.workflow_id,
            workflow_run_id=info.workflow_run_id,
            started_at=time.monotonic(),
        )
        telemetry._capture("started")
        return telemetry

    def finish(
        self,
        status: _TerminalStatus,
        *,
        counts: dict[str, int] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._capture(
            status,
            duration_seconds=time.monotonic() - self.started_at,
            counts=counts,
            error_type=None if error is None else type(error).__name__,
        )

    def _capture(
        self,
        status: Literal["started", "completed", "failed", "cancelled"],
        *,
        duration_seconds: float | None = None,
        counts: dict[str, int] | None = None,
        error_type: str | None = None,
    ) -> None:
        capture_account_property_sync_event(
            team_id=self.team_id,
            saved_query_id=self.saved_query_id,
            job_id=self.job_id,
            segment=self.segment,
            path=self.path,
            scope="attempt",
            status=status,
            source_id=self.source_id,
            duration_seconds=duration_seconds,
            attempt=self.attempt,
            counts=counts,
            error_type=error_type,
            workflow_id=self.workflow_id,
            workflow_run_id=self.workflow_run_id,
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
            continue
        capture_account_property_sync_event(
            team_id=input.team_id,
            saved_query_id=input.saved_query_id,
            job_id=input.job_id,
            segment=segment,
            path="legacy",
            scope="segment",
            status="started",
            workflow_id=workflow_id,
        )


@activity.defn
async def sync_warehouse_account_properties_activity(input: AccountPropertySyncInput) -> dict[str, int]:
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
    telemetry = _AttemptTelemetry.start(
        team_id=input.team_id,
        saved_query_id=input.saved_query_id,
        job_id=input.job_id,
        segment=segment.value,
        path="legacy",
    )
    started = time.monotonic()
    try:
        async with Heartbeater():
            result = await run_account_property_segment_sync(
                team_id=input.team_id,
                binding=saved_query_binding(input.saved_query_id),
                job_id=input.job_id,
                segment=segment,
                final_attempt=activity_info.attempt >= ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS,
            )
    except AccountPropertySourceValueError as error:
        ACCOUNT_PROPERTY_SYNC_TOTAL.labels(team_id=str(input.team_id), segment=segment.value, outcome="failed").inc()
        telemetry.finish("failed", error=error)
        log.warning("Account-property segment sync rejected invalid source values", error=str(error))
        raise ApplicationError(str(error), non_retryable=True) from error
    except asyncio.CancelledError:
        telemetry.finish("cancelled")
        raise
    except Exception as error:
        ACCOUNT_PROPERTY_SYNC_TOTAL.labels(team_id=str(input.team_id), segment=segment.value, outcome="failed").inc()
        telemetry.finish("failed", error=error)
        log.exception("Account-property segment sync failed")
        capture_exception(error)
        raise

    ACCOUNT_PROPERTY_SYNC_TOTAL.labels(team_id=str(input.team_id), segment=segment.value, outcome="completed").inc()
    ACCOUNT_PROPERTY_SYNC_DURATION_SECONDS.labels(segment=segment.value).observe(time.monotonic() - started)
    telemetry.finish("completed", counts=result)
    log.info("Account-property segment sync completed", **result)
    return result


@activity.defn(name="emit-warehouse-account-property-segment-telemetry")
async def emit_warehouse_account_property_segment_telemetry_activity(
    input: AccountPropertySegmentTelemetryInput,
) -> None:
    activity_info = activity.info()
    capture_account_property_sync_event(
        team_id=input.team_id,
        saved_query_id=input.saved_query_id,
        job_id=input.job_id,
        segment=input.segment,
        path=input.path,
        scope="segment",
        status=input.status,
        duration_seconds=input.duration_seconds,
        source_count=input.source_count,
        counts=input.counts,
        error_type=input.error_type,
        workflow_id=activity_info.workflow_id,
        workflow_run_id=activity_info.workflow_run_id,
    )


async def _emit_segment_telemetry(
    input: AccountPropertySyncInput,
    *,
    path: _SyncPath,
    status: _TerminalStatus,
    started_at: float,
    source_count: int | None = None,
    counts: dict[str, int] | None = None,
    error: BaseException | None = None,
) -> None:
    # Workflow code runs again on replay, so it sends the event through an activity, and it measures
    # the duration with the deterministic workflow clock.
    try:
        await workflow.execute_activity(
            emit_warehouse_account_property_segment_telemetry_activity,
            AccountPropertySegmentTelemetryInput(
                team_id=input.team_id,
                saved_query_id=input.saved_query_id,
                job_id=input.job_id,
                segment=input.segment,
                path=path,
                status=status,
                duration_seconds=max(workflow.time() - started_at, 0.0),
                source_count=source_count,
                counts=counts,
                error_type=None if error is None else _failure_type(error),
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
    except ActivityError:
        workflow.logger.warning(
            "Account-property segment telemetry failed",
            extra={"job_id": input.job_id, "segment": input.segment, "path": path},
        )


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
        # Histories recorded before the patch have no telemetry activity, so replay must skip it.
        telemetry_enabled = workflow.patched(ACCOUNT_PROPERTY_SEGMENT_TELEMETRY_PATCH)
        started_at = workflow.time()
        try:
            counts = await workflow.execute_activity(
                sync_warehouse_account_properties_activity,
                input,
                start_to_close_timeout=timedelta(hours=6),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS,
                    initial_interval=timedelta(seconds=30),
                ),
            )
        except (asyncio.CancelledError, Exception) as error:
            if telemetry_enabled:
                await _emit_segment_telemetry(
                    input,
                    path="legacy",
                    status="cancelled" if is_cancelled_exception(error) else "failed",
                    started_at=started_at,
                    error=error,
                )
            raise
        if telemetry_enabled:
            await _emit_segment_telemetry(
                input, path="legacy", status="completed", started_at=started_at, counts=counts
            )


ACCOUNT_PROPERTY_SYNC_WORKFLOWS = [
    StageWarehouseAccountPropertiesWorkflow,
    SyncWarehouseAccountPropertiesWorkflow,
]
ACCOUNT_PROPERTY_SYNC_ACTIVITIES = [
    start_warehouse_account_property_runs_activity,
    finalize_warehouse_account_property_runs_activity,
    stage_warehouse_account_property_files_activity,
    dispatch_warehouse_account_property_sync_activity,
    sync_warehouse_account_properties_activity,
    emit_warehouse_account_property_segment_telemetry_activity,
]
