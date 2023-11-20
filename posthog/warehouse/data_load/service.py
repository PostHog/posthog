from datetime import timedelta
from posthog import settings
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleSpec,
    ScheduleIntervalSpec,
    ScheduleState,
    SchedulePolicy,
    ScheduleOverlapPolicy,
)
from dataclasses import asdict
from posthog.warehouse.models import ExternalDataSource

from posthog.temporal.client import sync_connect
from posthog.temporal.workflows.external_data_job import ExternalDataJobWorkflow, ExternalDataJobInputs
from posthog.temporal.schedule import (
    create_schedule,
    update_schedule,
    trigger_schedule,
    pause_schedule,
)


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
            task_queue=settings.TEMPORAL_EXTERNAL_DATA_JOB_TASK_QUEUE,
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
