import logging
from dataclasses import asdict
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction

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
from posthog.temporal.data_modeling.run_workflow import RunWorkflowInputs, Selector
from posthog.warehouse.models import DataWarehouseModelPath
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery

if TYPE_CHECKING:
    from posthog.warehouse.models import DataWarehouseSavedQuery


def get_sync_frequency(saved_query: "DataWarehouseSavedQuery") -> tuple[timedelta, timedelta]:
    interval = saved_query.sync_frequency_interval or timedelta(hours=24)

    if interval <= timedelta(hours=1):
        return (interval, timedelta(minutes=1))
    if interval <= timedelta(hours=12):
        return (interval, timedelta(minutes=30))

    return (interval, timedelta(hours=1))


def get_saved_query_schedule(saved_query: "DataWarehouseSavedQuery") -> Schedule:
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


def delete_saved_query_schedule(schedule_id: str):
    temporal = sync_connect()
    try:
        delete_schedule(temporal, schedule_id=schedule_id)
    except temporalio.service.RPCError as e:
        # Swallow error if schedule does not exist already
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            return
        raise


def pause_saved_query_schedule(id: str) -> None:
    temporal = sync_connect()
    pause_schedule(temporal, schedule_id=id)


def unpause_saved_query_schedule(id: str) -> None:
    temporal = sync_connect()
    unpause_schedule(temporal, schedule_id=id)


def saved_query_workflow_exists(id: str) -> bool:
    temporal = sync_connect()
    return schedule_exists(temporal, schedule_id=id)


def trigger_saved_query_schedule(saved_query: "DataWarehouseSavedQuery"):
    temporal = sync_connect()
    trigger_schedule(temporal, schedule_id=str(saved_query.id))


def recreate_model_paths(saved_query: DataWarehouseSavedQuery) -> None:
    """
    Recreate model paths for a saved query after materialization.
    After a query has been reverted and then re-materialized, we need to ensure
    the model paths exist for the temporal workflow to properly build the DAG.
    """

    try:
        with transaction.atomic():
            if not DataWarehouseModelPath.objects.filter(
                team=saved_query.team, path__contains=[saved_query.id.hex]
            ).exists():
                DataWarehouseModelPath.objects.update_or_create(team=saved_query.team, path=[saved_query.id.hex])
                for table_name in saved_query.s3_tables:
                    DataWarehouseModelPath.objects.update_or_create(
                        team=saved_query.team, path=[table_name, saved_query.id.hex]
                    )
    except Exception as e:
        logging.exception(f"Failed to recreate model paths for {saved_query.id}: {str(e)}")
        raise
