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
    DEFAULT_ACCOUNT_PROPERTY_SOURCE_CONCURRENCY,
    AccountPropertySegmentTelemetryInput,
    AccountPropertySourceSyncInput,
    AccountPropertySyncInput,
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

    from posthog.sync import database_sync_to_async, database_sync_to_async_pool
    from posthog.temporal.common.client import async_connect

    from products.customer_analytics.backend.logic.account_property_fanout_flags import (
        account_property_sync_fanout_enabled,
        get_account_property_sync_source_concurrency,
    )
    from products.customer_analytics.backend.logic.account_property_runs import (
        AccountPropertySyncRunContext,
        AccountPropertySyncSegmentIncompleteError,
        finalize_account_property_sync_runs,
        start_account_property_sync_runs,
        update_account_property_sync_runs_phase,
    )
    from products.customer_analytics.backend.logic.account_property_sync import (
        AccountPropertySourceRejectedError,
        AccountPropertySourceValueError,
        AccountPropertySyncSegment,
        SourceSyncCheckpoint,
        complete_account_property_sync_segment,
        get_account_property_sync_source_ids,
        run_account_property_segment_sync,
        run_account_property_source_sync,
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
ACCOUNT_PROPERTY_SYNC_FANOUT_WORKFLOW_NAME = "sync-warehouse-account-properties-fanout"
ACCOUNT_PROPERTY_RUN_HISTORY_PATCH = "account-property-run-history-2026-08"
ACCOUNT_PROPERTY_SEGMENT_TELEMETRY_PATCH = "account-property-segment-telemetry-2026-10"
ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS = 5
# Source IDs are UUID strings, so this keeps the discovery result far below the 256 KB field rule.
ACCOUNT_PROPERTY_FANOUT_MAX_SOURCES = 2_000

_STAGING_FAILED_ERROR = (
    "Couldn't prepare warehouse rows. Run the source view again. If it keeps failing, contact support."
)
_DISPATCH_FAILED_ERROR = (
    "Couldn't start account updates. Run the source view again. If it keeps failing, contact support."
)
_SYNC_FAILED_ERROR = "Couldn't update accounts. Run the source view again. If it keeps failing, contact support."
_SOURCE_SYNC_FAILED_ERROR_TYPE = "AccountPropertySourceSyncFailed"

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


def _segment_workflow_id(job_id: str, segment: str) -> str:
    # Both workflow types share this ID, so a retried dispatch can't start a second path for a segment.
    return f"sync-warehouse-account-properties-{job_id}-{segment}"


def _failure_type(error: BaseException) -> str:
    cause = error.cause if isinstance(error, ActivityError) and error.cause is not None else error
    if isinstance(cause, ApplicationError) and cause.type:
        return cause.type
    return type(cause).__name__


def _failure_counts(error: BaseException) -> dict[str, int] | None:
    cause = error.cause if isinstance(error, ActivityError) and error.cause is not None else error
    if not isinstance(cause, ApplicationError) or cause.type != "AccountPropertySourceValueError":
        return None
    if not cause.details or not isinstance(cause.details[0], dict):
        return None
    return {
        key: value
        for key, value in cause.details[0].items()
        if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool)
    }


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
            source_count=None if counts is None else counts.get("source_count"),
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
        segment=None if input.segment is None else AccountPropertySyncSegment(input.segment),
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
    # Evaluated once per dispatch so both segments of this attempt start the same workflow type. A flag
    # change only affects segments that are not started yet, because both types share one workflow ID.
    use_fanout = await database_sync_to_async_pool(account_property_sync_fanout_enabled)(input.team_id)
    workflow_name = ACCOUNT_PROPERTY_SYNC_FANOUT_WORKFLOW_NAME if use_fanout else ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME
    path: _SyncPath = "fanout" if use_fanout else "legacy"
    source_concurrency = (
        await database_sync_to_async_pool(get_account_property_sync_source_concurrency)(input.team_id)
        if use_fanout
        else DEFAULT_ACCOUNT_PROPERTY_SOURCE_CONCURRENCY
    )
    client = await async_connect()
    for segment in ("tracked", "ignored"):
        try:
            await client.start_workflow(
                workflow_name,
                AccountPropertySyncInput(
                    team_id=input.team_id,
                    saved_query_id=input.saved_query_id,
                    job_id=input.job_id,
                    segment=segment,
                    source_concurrency=source_concurrency,
                ),
                id=_segment_workflow_id(input.job_id, segment),
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
            path=path,
            scope="segment",
            status="started",
            workflow_id=_segment_workflow_id(input.job_id, segment),
        )
        logger.info(
            "Account-property segment sync started",
            team_id=input.team_id,
            job_id=input.job_id,
            segment=segment,
            path=path,
            source_concurrency=source_concurrency,
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
        telemetry.finish("failed", counts=error.counts, error=error)
        log.warning("Account-property segment sync rejected invalid source values", error=str(error))
        raise ApplicationError(str(error), error.counts, type=type(error).__name__, non_retryable=True) from error
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


@activity.defn(name="list-warehouse-account-property-sources")
async def list_warehouse_account_property_sources_activity(input: AccountPropertySyncInput) -> list[str]:
    source_ids = await database_sync_to_async(get_account_property_sync_source_ids, thread_sensitive=False)(
        input.team_id, saved_query_binding(input.saved_query_id)
    )
    if len(source_ids) > ACCOUNT_PROPERTY_FANOUT_MAX_SOURCES:
        raise ApplicationError(
            f"View has {len(source_ids)} account-property sources, above the fanout limit of "
            f"{ACCOUNT_PROPERTY_FANOUT_MAX_SOURCES}",
            type="AccountPropertyFanoutSourceLimitExceeded",
            non_retryable=True,
        )
    return source_ids


@activity.defn(name="sync-warehouse-account-property-source")
async def sync_warehouse_account_property_source_activity(input: AccountPropertySourceSyncInput) -> dict[str, int]:
    segment = AccountPropertySyncSegment(input.segment)
    activity_info = activity.info()
    log = logger.bind(
        team_id=input.team_id,
        saved_query_id=input.saved_query_id,
        job_id=input.job_id,
        segment=segment.value,
        source_id=input.source_id,
    )
    telemetry = _AttemptTelemetry.start(
        team_id=input.team_id,
        saved_query_id=input.saved_query_id,
        job_id=input.job_id,
        segment=segment.value,
        path="fanout",
        source_id=input.source_id,
    )
    try:
        source_uuid = UUID(input.source_id)
    except ValueError as error:
        telemetry.finish("failed", error=error)
        raise ApplicationError("Account-property source ID is not a UUID", non_retryable=True) from error
    try:
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
            source_id=source_uuid,
        )
        resume_from = SourceSyncCheckpoint.from_heartbeat_details(activity_info.heartbeat_details)
        async with Heartbeater() as heartbeater:

            def save_checkpoint(checkpoint: SourceSyncCheckpoint) -> None:
                heartbeater.details = (checkpoint.to_heartbeat_details(),)

            if resume_from is not None:
                save_checkpoint(resume_from)
            result = await run_account_property_source_sync(
                team_id=input.team_id,
                binding=saved_query_binding(input.saved_query_id),
                job_id=input.job_id,
                segment=segment,
                source_id=input.source_id,
                final_attempt=activity_info.attempt >= ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS,
                resume_from=resume_from,
                save_checkpoint=save_checkpoint,
            )
    except (AccountPropertySourceValueError, AccountPropertySourceRejectedError) as error:
        # A retry reads the same staged rows and source config, so it can't fix these errors.
        failure_counts = error.counts if isinstance(error, AccountPropertySourceValueError) else None
        telemetry.finish("failed", counts=failure_counts, error=error)
        log.warning("Account-property source sync rejected", error_type=type(error).__name__)
        details = () if failure_counts is None else (failure_counts,)
        raise ApplicationError(str(error), *details, type=type(error).__name__, non_retryable=True) from error
    except asyncio.CancelledError:
        telemetry.finish("cancelled")
        raise
    except Exception as error:
        telemetry.finish("failed", error=error)
        log.exception("Account-property source sync failed")
        capture_exception(error)
        raise

    telemetry.finish("completed", counts=result)
    log.info("Account-property source sync completed", **result)
    return result


@activity.defn(name="complete-warehouse-account-property-segment")
async def complete_warehouse_account_property_segment_activity(input: AccountPropertySyncInput) -> None:
    try:
        async with Heartbeater():
            await complete_account_property_sync_segment(
                team_id=input.team_id,
                binding=saved_query_binding(input.saved_query_id),
                job_id=input.job_id,
                segment=AccountPropertySyncSegment(input.segment),
            )
    except AccountPropertySyncSegmentIncompleteError as error:
        raise ApplicationError(str(error), type=type(error).__name__, non_retryable=True) from error


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
            schedule_to_close_timeout=timedelta(minutes=3),
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
                failure_counts = _failure_counts(error)
                await _emit_segment_telemetry(
                    input,
                    path="legacy",
                    status="cancelled" if is_cancelled_exception(error) else "failed",
                    started_at=started_at,
                    source_count=None if failure_counts is None else failure_counts.get("source_count"),
                    counts=failure_counts,
                    error=error,
                )
            raise
        if telemetry_enabled:
            await _emit_segment_telemetry(
                input,
                path="legacy",
                status="completed",
                started_at=started_at,
                source_count=counts.get("source_count"),
                counts=counts,
            )


@frozen
class _SettledSources:
    counts: dict[str, int]
    failed: int


async def _sync_sources(input: AccountPropertySyncInput, source_ids: list[str]) -> _SettledSources:
    semaphore = asyncio.Semaphore(input.source_concurrency)

    async def sync_source(source_id: str) -> dict[str, int]:
        async with semaphore:
            return await workflow.execute_activity(
                sync_warehouse_account_property_source_activity,
                AccountPropertySourceSyncInput(
                    team_id=input.team_id,
                    saved_query_id=input.saved_query_id,
                    job_id=input.job_id,
                    segment=input.segment,
                    source_id=source_id,
                ),
                activity_id=f"sync-account-property-source-{source_id}",
                start_to_close_timeout=timedelta(hours=6),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS,
                    initial_interval=timedelta(seconds=30),
                ),
            )

    # return_exceptions keeps one failed source from ending the gather while its siblings still run.
    # The coordinator must not finalize the segment before every source activity settles.
    results = await asyncio.gather(*(sync_source(source_id) for source_id in source_ids), return_exceptions=True)
    counts: dict[str, int] = {}
    failed = 0
    for result in results:
        if isinstance(result, BaseException):
            failed += 1
            continue
        for key, value in result.items():
            counts[key] = counts.get(key, 0) + value
    counts["source_errors"] = failed
    return _SettledSources(counts=counts, failed=failed)


@workflow.defn(name=ACCOUNT_PROPERTY_SYNC_FANOUT_WORKFLOW_NAME)
class SyncWarehouseAccountPropertiesFanoutWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> AccountPropertySyncInput:
        return AccountPropertySyncInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, input: AccountPropertySyncInput) -> None:
        started_at = workflow.time()
        source_count: int | None = None
        counts: dict[str, int] | None = None
        try:
            listed_source_ids = await workflow.execute_activity(
                list_warehouse_account_property_sources_activity,
                input,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS),
            )
            source_ids = list(dict.fromkeys(listed_source_ids))
            source_count = len(source_ids)
            settled = await _sync_sources(input, source_ids)
            counts = settled.counts
            if settled.failed:
                raise ApplicationError(
                    f"{settled.failed} of {source_count} account-property sources failed",
                    type=_SOURCE_SYNC_FAILED_ERROR_TYPE,
                    non_retryable=True,
                )
            await workflow.execute_activity(
                complete_warehouse_account_property_segment_activity,
                input,
                start_to_close_timeout=timedelta(hours=1),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS,
                    initial_interval=timedelta(seconds=30),
                ),
            )
        except (asyncio.CancelledError, Exception) as error:
            # Workflow eviction raises a BaseException that is not caught here, so cleanup runs only for
            # a real failure or cancellation.
            cancelled = is_cancelled_exception(error)
            try:
                if not cancelled:
                    # Closes only the runs still open in this segment. Completed sibling runs keep their
                    # result, and the staged rows stay in place for the next run of the source view.
                    await workflow.execute_activity(
                        finalize_warehouse_account_property_runs_activity,
                        FinalizeAccountPropertySyncRunsInput(
                            team_id=input.team_id,
                            saved_query_id=input.saved_query_id,
                            job_id=input.job_id,
                            status=SyncStatus.FAILED.value,
                            phase=SyncPhase.SYNCING.value,
                            error=_SYNC_FAILED_ERROR,
                            segment=input.segment,
                        ),
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=ACCOUNT_PROPERTY_ACTIVITY_MAX_ATTEMPTS),
                    )
            finally:
                await _emit_segment_telemetry(
                    input,
                    path="fanout",
                    status="cancelled" if cancelled else "failed",
                    started_at=started_at,
                    source_count=source_count,
                    counts=counts,
                    error=error,
                )
            raise
        await _emit_segment_telemetry(
            input,
            path="fanout",
            status="completed",
            started_at=started_at,
            source_count=source_count,
            counts=counts,
        )


ACCOUNT_PROPERTY_SYNC_WORKFLOWS = [
    StageWarehouseAccountPropertiesWorkflow,
    SyncWarehouseAccountPropertiesWorkflow,
    SyncWarehouseAccountPropertiesFanoutWorkflow,
]
ACCOUNT_PROPERTY_SYNC_ACTIVITIES = [
    start_warehouse_account_property_runs_activity,
    finalize_warehouse_account_property_runs_activity,
    stage_warehouse_account_property_files_activity,
    dispatch_warehouse_account_property_sync_activity,
    sync_warehouse_account_properties_activity,
    list_warehouse_account_property_sources_activity,
    sync_warehouse_account_property_source_activity,
    complete_warehouse_account_property_segment_activity,
    emit_warehouse_account_property_segment_telemetry_activity,
]
