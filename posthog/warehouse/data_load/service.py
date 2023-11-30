from dataclasses import asdict
from datetime import timedelta

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)

from posthog.constants import DATA_WAREHOUSE_TASK_QUEUE
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import (
    create_schedule,
    pause_schedule,
    trigger_schedule,
    update_schedule,
    delete_schedule,
)
from posthog.temporal.data_imports.external_data_job import (
    ExternalDataJobInputs,
    ExternalDataJobWorkflow,
)
from posthog.warehouse.models import ExternalDataSource
import temporalio


def sync_external_data_job_workflow(external_data_source: ExternalDataSource, create: bool = False) -> str:
    temporal = sync_connect()
    inputs = ExternalDataJobInputs(
        team_id=external_data_source.team.id,
        external_data_source_id=external_data_source.pk,
    )

    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            ExternalDataJobWorkflow.run,
            asdict(inputs),
            id=str(external_data_source.pk),
            task_queue=DATA_WAREHOUSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=24))]),
        state=ScheduleState(note=f"Schedule for external data source: {external_data_source.pk}"),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.CANCEL_OTHER),
    )

    if create:
        create_schedule(temporal, id=str(external_data_source.id), schedule=schedule, trigger_immediately=True)
    else:
        update_schedule(temporal, id=str(external_data_source.id), schedule=schedule)

    return external_data_source


def trigger_external_data_workflow(external_data_source: ExternalDataSource):
    temporal = sync_connect()
    trigger_schedule(temporal, schedule_id=str(external_data_source.id))


def pause_external_data_workflow(external_data_source: ExternalDataSource):
    temporal = sync_connect()
    pause_schedule(temporal, schedule_id=str(external_data_source.id))


def delete_external_data_workflow(external_data_source: ExternalDataSource):
    temporal = sync_connect()
    try:
        delete_schedule(temporal, schedule_id=str(external_data_source.id))
    except temporalio.service.RPCError as e:
        # Swallow error if schedule does not exist already
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            return
        raise
