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

from posthog.constants import DATA_MODELING_TASK_QUEUE
from posthog.temporal.common.client import sync_connect
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

if TYPE_CHECKING:
    from posthog.warehouse.models import DataWarehouseSavedQuery


def sync_saved_query_snapshot_workflow(
    saved_query: "DataWarehouseSavedQuery", create: bool = False
) -> "DataWarehouseSavedQuery":
    temporal = sync_connect()
    schedule = get_snapshot_schedule(saved_query)
    if create:
        create_schedule(temporal, id=str(saved_query.id) + "-snapshot", schedule=schedule)
    else:
        update_schedule(temporal, id=str(saved_query.id) + "-snapshot", schedule=schedule)

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
            id=str(saved_query.id) + "-snapshot",
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
    pause_schedule(temporal, schedule_id=id)


def unpause_snapshot_schedule(id: str) -> None:
    temporal = sync_connect()
    unpause_schedule(temporal, schedule_id=id)


def snapshot_workflow_exists(id: str) -> bool:
    temporal = sync_connect()
    return schedule_exists(temporal, schedule_id=id)


def trigger_snapshot_schedule(saved_query: "DataWarehouseSavedQuery"):
    temporal = sync_connect()
    trigger_schedule(temporal, schedule_id=str(saved_query.id) + "-snapshot")
