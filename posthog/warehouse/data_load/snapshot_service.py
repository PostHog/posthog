import uuid
from dataclasses import asdict
from datetime import timedelta
from typing import TYPE_CHECKING

import temporalio
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.common import RetryPolicy

from posthog.constants import DATA_MODELING_TASK_QUEUE
from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.common.schedule import (
    create_schedule,
    delete_schedule,
    pause_schedule,
    schedule_exists,
    trigger_schedule,
    unpause_schedule,
    update_schedule,
)
from posthog.temporal.hogql_query_snapshots.run_workflow import RunWorkflowInputs
from posthog.warehouse.models.datawarehouse_saved_query import aget_saved_query_by_id

if TYPE_CHECKING:
    from posthog.warehouse.models import DataWarehouseSavedQuery

SNAPSHOT_SUFFIX = "-snapshot"


def sync_saved_query_snapshot_workflow(
    saved_query: "DataWarehouseSavedQuery", create: bool = False
) -> "DataWarehouseSavedQuery":
    temporal = sync_connect()
    schedule = get_snapshot_schedule(saved_query)
    if create:
        create_schedule(temporal, id=str(saved_query.id) + SNAPSHOT_SUFFIX, schedule=schedule)
    else:
        update_schedule(temporal, id=str(saved_query.id) + SNAPSHOT_SUFFIX, schedule=schedule)

    return saved_query


def get_snapshot_schedule(saved_query: "DataWarehouseSavedQuery") -> Schedule:
    inputs = RunWorkflowInputs(
        team_id=saved_query.team_id,
        saved_query_id=str(saved_query.id),
    )

    return Schedule(
        action=ScheduleActionStartWorkflow(
            "hogql-query-snapshots-run",
            asdict(inputs),
            id=str(saved_query.id) + SNAPSHOT_SUFFIX,
            # reuse queue for now
            task_queue=str(DATA_MODELING_TASK_QUEUE),
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(days=1))],
            jitter=timedelta(minutes=15),
        ),
        state=ScheduleState(note=f"Schedule for saved query snapshot: {saved_query.pk}"),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


def delete_snapshot_schedule(schedule_id: str) -> None:
    temporal = sync_connect()
    try:
        delete_schedule(temporal, schedule_id=schedule_id)
    except temporalio.service.RPCError as e:
        # Swallow error if schedule does not exist already
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            return
        raise


def pause_snapshot_schedule(id: str) -> None:
    temporal = sync_connect()
    pause_schedule(temporal, schedule_id=id + SNAPSHOT_SUFFIX)


def unpause_snapshot_schedule(id: str) -> None:
    temporal = sync_connect()
    unpause_schedule(temporal, schedule_id=id + SNAPSHOT_SUFFIX)


def snapshot_workflow_exists(id: str) -> bool:
    temporal = sync_connect()
    return schedule_exists(temporal, schedule_id=id + SNAPSHOT_SUFFIX)


def trigger_snapshot_schedule(saved_query: "DataWarehouseSavedQuery"):
    temporal = sync_connect()
    trigger_schedule(temporal, schedule_id=str(saved_query.id) + SNAPSHOT_SUFFIX)


async def start_snapshot_workflow(label: str, team_id: int) -> None:
    """Start the snapshot workflow and return its handle."""

    model_id = uuid.UUID(label)
    workflow_id = f"hogql-query-snapshots-run-{model_id}"

    saved_query = await aget_saved_query_by_id(str(model_id), team_id)

    if saved_query is not None and saved_query.snapshot_enabled:
        inputs = RunWorkflowInputs(
            team_id=team_id,
            saved_query_id=str(model_id),
        )

        client = await async_connect()
        await client.start_workflow(
            "hogql-query-snapshots-run",
            inputs,
            id=workflow_id,
            task_queue=str(DATA_MODELING_TASK_QUEUE),
            retry_policy=RetryPolicy(
                maximum_attempts=1,
            ),
        )

    return
