from dataclasses import asdict
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings

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

from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.common.schedule import (
    a_pause_schedule,
    create_schedule,
    delete_schedule,
    pause_schedule,
    schedule_exists,
    trigger_schedule,
    unpause_schedule,
    update_schedule,
)

if TYPE_CHECKING:
    from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


def get_sync_frequency(saved_query: "DataWarehouseSavedQuery") -> tuple[timedelta, timedelta]:
    interval = saved_query.sync_frequency_interval or timedelta(hours=24)

    if interval <= timedelta(hours=1):
        return (interval, timedelta(minutes=1))
    if interval <= timedelta(hours=12):
        return (interval, timedelta(minutes=30))

    return (interval, timedelta(hours=1))


def get_saved_query_schedule(saved_query: "DataWarehouseSavedQuery") -> Schedule:
    from posthog.temporal.data_modeling.run_workflow import RunWorkflowInputs, Selector

    inputs = RunWorkflowInputs(
        team_id=saved_query.team_id,
        select=[Selector(label=saved_query.id.hex, ancestors=0, descendants=0)],
    )

    sync_frequency, jitter = get_sync_frequency(saved_query)

    return Schedule(
        action=ScheduleActionStartWorkflow(
            "data-modeling-run",
            asdict(inputs),
            id=str(saved_query.id),
            task_queue=str(settings.DATA_MODELING_TASK_QUEUE),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=10),
                maximum_interval=timedelta(seconds=60),
                maximum_attempts=3,
                non_retryable_error_types=["NondeterminismError", "CancelledError"],
            ),
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=sync_frequency)],
            jitter=jitter,
        ),
        state=ScheduleState(note=f"Schedule for saved query: {saved_query.pk}"),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


def sync_saved_query_workflow(
    saved_query: "DataWarehouseSavedQuery", create: bool = False
) -> "DataWarehouseSavedQuery":
    temporal = sync_connect()
    schedule = get_saved_query_schedule(saved_query)

    if create:
        create_schedule(temporal, id=str(saved_query.id), schedule=schedule, trigger_immediately=True)
    else:
        update_schedule(temporal, id=str(saved_query.id), schedule=schedule)

    return saved_query


def delete_saved_query_schedule(saved_query: "DataWarehouseSavedQuery"):
    temporal = sync_connect()
    try:
        delete_schedule(temporal, schedule_id=str(saved_query.id))
    except temporalio.service.RPCError as e:
        # Swallow error if schedule does not exist already
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            return
        raise


def pause_saved_query_schedule(saved_query: "DataWarehouseSavedQuery") -> None:
    temporal = sync_connect()
    pause_schedule(temporal, schedule_id=str(saved_query.id))


async def a_pause_saved_query_schedule(saved_query: "DataWarehouseSavedQuery") -> None:
    temporal = await async_connect()
    await a_pause_schedule(temporal, schedule_id=str(saved_query.id))


def unpause_saved_query_schedule(saved_query: "DataWarehouseSavedQuery") -> None:
    temporal = sync_connect()
    unpause_schedule(temporal, schedule_id=str(saved_query.id))
    # reset the automatic sync interval for rev analytics
    viewset = saved_query.managed_viewset
    if viewset and viewset.kind == "revenue_analytics":
        saved_query.sync_frequency_interval = timedelta(hours=12)
        saved_query.save()


def saved_query_workflow_exists(saved_query: "DataWarehouseSavedQuery") -> bool:
    temporal = sync_connect()
    return schedule_exists(temporal, schedule_id=str(saved_query.id))


def trigger_saved_query_schedule(saved_query: "DataWarehouseSavedQuery"):
    temporal = sync_connect()
    trigger_schedule(temporal, schedule_id=str(saved_query.id))
