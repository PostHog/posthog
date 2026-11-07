import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from threading import Event
from time import monotonic

from temporalio import activity, workflow
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import RetryPolicy
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    TimeoutError as ActivityTimeoutError,
)
from temporalio.service import RPCError, RPCStatusCode

with workflow.unsafe.imports_passed_through():
    import structlog

    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.client import async_connect
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.customer_analytics.backend.facade.membership_snapshot_contracts import (
        MembershipSnapshotBatch,
        MembershipSnapshotCheckpoint,
        MembershipSnapshotInput,
        MembershipSnapshotStatus,
        MembershipSnapshotStep,
    )
    from products.customer_analytics.backend.logic.membership_snapshot_backfill import (
        load_membership_snapshot,
        prepare_membership_snapshot,
    )
    from products.customer_analytics.backend.temporal.membership_backfill import SCHEDULE_ID, get_membership_workflow_id
    from products.data_modeling.backend.facade.contracts import MaterializedQuerySnapshot

LOGGER = structlog.get_logger(__name__)
WORKFLOW_NAME = "customer-analytics-membership-snapshot-backfill"


def get_membership_snapshot_workflow_id(team_id: int) -> str:
    return f"{WORKFLOW_NAME}-{team_id}"


def restore_snapshot_checkpoint(value: object) -> MembershipSnapshotCheckpoint:
    if not isinstance(value, dict):
        raise ValueError("Invalid membership snapshot checkpoint")
    return MembershipSnapshotCheckpoint(**value)


async def check_membership_writers_paused(team_id: int) -> None:
    client = await async_connect()
    schedule = await client.get_schedule_handle(SCHEDULE_ID).describe()
    if not schedule.schedule.state.paused:
        raise ValueError("Pause the membership coordinator before starting a snapshot backfill")
    try:
        native = await client.get_workflow_handle(get_membership_workflow_id(team_id)).describe()
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND:
            return
        raise
    if native.status == WorkflowExecutionStatus.RUNNING:
        raise ValueError("Close the existing event backfill before starting a snapshot backfill")


@activity.defn
async def prepare_membership_snapshot_activity(input: MembershipSnapshotInput) -> MaterializedQuerySnapshot:
    async with Heartbeater():
        if not input.dry_run:
            await check_membership_writers_paused(input.team_id)
        return await database_sync_to_async(prepare_membership_snapshot, thread_sensitive=False)(input)


@activity.defn
async def load_membership_snapshot_activity(batch: MembershipSnapshotBatch) -> MembershipSnapshotStep:
    stopped = Event()
    checkpoint = batch.checkpoint
    if activity.info().heartbeat_details:
        checkpoint = restore_snapshot_checkpoint(activity.info().heartbeat_details[0])
    async with Heartbeater(details=(asdict(checkpoint),)) as heartbeater:

        def record_checkpoint(value: MembershipSnapshotCheckpoint) -> None:
            nonlocal checkpoint
            checkpoint = value
            heartbeater.details = (asdict(value),)
            LOGGER.info(
                "customer_analytics.membership_snapshot_backfill",
                team_id=batch.input.team_id,
                dry_run=batch.input.dry_run,
                rows_read=value.rows_read,
                rows_written=value.rows_written,
                batches=value.batches,
            )

        try:
            if not batch.input.dry_run:
                await check_membership_writers_paused(batch.input.team_id)
            return await load_membership_snapshot(
                replace(batch, checkpoint=checkpoint),
                deadline=monotonic() + 270,
                should_stop=lambda: stopped.is_set() or activity.is_cancelled() or activity.is_worker_shutdown(),
                on_checkpoint=record_checkpoint,
            )
        except Exception as error:
            raise ApplicationError(
                "Membership snapshot loading failed. Inspect the activity and resume after resolving its cause",
                asdict(checkpoint),
                type=type(error).__name__,
                non_retryable=isinstance(error, ValueError),
            ) from error
        finally:
            stopped.set()


@workflow.defn(name=WORKFLOW_NAME)
class MembershipSnapshotBackfillWorkflow:
    def __init__(self) -> None:
        self.input: MembershipSnapshotInput | None = None
        self.status = MembershipSnapshotStatus()
        self.checkpoint = MembershipSnapshotCheckpoint()
        self.snapshot: MaterializedQuerySnapshot | None = None
        self.resume_requested = False
        self.cancel_requested = False

    @staticmethod
    def parse_inputs(inputs: list[str]) -> MembershipSnapshotInput:
        values = json.loads(inputs[0])
        values["checked_at"] = datetime.fromisoformat(values["checked_at"])
        return MembershipSnapshotInput(**values)

    @workflow.query
    def get_status(self) -> MembershipSnapshotStatus:
        return replace(
            self.status,
            row_limit=self.input.max_rows if self.input else 0,
            expected_rows=self.input.expected_rows if self.input else 0,
            dry_run=self.input.dry_run if self.input else True,
            rows_read=self.checkpoint.rows_read,
            rows_written=self.checkpoint.rows_written,
            batches=self.checkpoint.batches,
        )

    @workflow.signal
    def resume(self) -> None:
        if self.status.status == "failed":
            self.resume_requested = True

    @workflow.signal
    def cancel(self) -> None:
        self.cancel_requested = True

    def restore_failure_checkpoint(self, error: ActivityError) -> None:
        cause = error.cause
        details = (
            cause.details
            if isinstance(cause, ApplicationError)
            else cause.last_heartbeat_details
            if isinstance(cause, ActivityTimeoutError)
            else ()
        )
        if details:
            checkpoint = restore_snapshot_checkpoint(details[0])
            if checkpoint.rows_read >= self.checkpoint.rows_read:
                self.checkpoint = checkpoint

    @workflow.run
    async def run(self, input: MembershipSnapshotInput) -> MembershipSnapshotStatus:
        if workflow.info().workflow_id != get_membership_snapshot_workflow_id(input.team_id):
            raise ApplicationError("Use the project membership snapshot workflow ID", non_retryable=True)
        self.input = input
        while not self.cancel_requested:
            try:
                self.status = MembershipSnapshotStatus(status="running")
                if self.snapshot is None:
                    self.snapshot = await workflow.execute_activity(
                        prepare_membership_snapshot_activity,
                        input,
                        start_to_close_timeout=timedelta(minutes=2),
                        heartbeat_timeout=timedelta(minutes=1),
                        retry_policy=RetryPolicy(
                            maximum_attempts=3,
                            non_retryable_error_types=["ValueError", "MembershipSnapshotRejectedError"],
                        ),
                    )
                step = await workflow.execute_activity(
                    load_membership_snapshot_activity,
                    MembershipSnapshotBatch(input=input, snapshot=self.snapshot, checkpoint=self.checkpoint),
                    start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                self.checkpoint = step.checkpoint
                if step.completed and not self.cancel_requested:
                    self.status = MembershipSnapshotStatus(status="completed")
                    return self.get_status()
            except ActivityError as error:
                self.restore_failure_checkpoint(error)
                cause = error.cause
                error_type = cause.type if isinstance(cause, ApplicationError) else type(cause).__name__
                self.status = MembershipSnapshotStatus(status="failed", error_type=error_type or "ActivityError")
                await workflow.wait_condition(lambda: self.resume_requested or self.cancel_requested)
                self.resume_requested = False
        self.status = MembershipSnapshotStatus(status="cancelled")
        return self.get_status()
