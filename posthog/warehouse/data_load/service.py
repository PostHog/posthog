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
    unpause_schedule,
)
from posthog.temporal.data_imports.external_data_job import (
    ExternalDataWorkflowInputs,
)
from posthog.warehouse.models import ExternalDataSource
import temporalio
from temporalio.client import Client as TemporalClient
from asgiref.sync import async_to_sync

from django.conf import settings
import s3fs


def sync_external_data_job_workflow(
    external_data_source: ExternalDataSource, create: bool = False
) -> ExternalDataSource:
    temporal = sync_connect()
    inputs = ExternalDataWorkflowInputs(
        team_id=external_data_source.team.id,
        external_data_source_id=external_data_source.pk,
    )

    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "external-data-job",
            asdict(inputs),
            id=str(external_data_source.pk),
            task_queue=str(DATA_WAREHOUSE_TASK_QUEUE),
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=timedelta(hours=24), offset=timedelta(hours=external_data_source.created_at.hour)
                )
            ],
            jitter=timedelta(hours=2),
        ),
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


def pause_external_data_schedule(external_data_source: ExternalDataSource):
    temporal = sync_connect()
    pause_schedule(temporal, schedule_id=str(external_data_source.id))


def unpause_external_data_schedule(external_data_source: ExternalDataSource):
    temporal = sync_connect()
    unpause_schedule(temporal, schedule_id=str(external_data_source.id))


def delete_external_data_schedule(external_data_source: ExternalDataSource):
    temporal = sync_connect()
    try:
        delete_schedule(temporal, schedule_id=str(external_data_source.id))
    except temporalio.service.RPCError as e:
        # Swallow error if schedule does not exist already
        if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
            return
        raise


def cancel_external_data_workflow(workflow_id: str):
    temporal = sync_connect()
    cancel_workflow(temporal, workflow_id)


@async_to_sync
async def cancel_workflow(temporal: TemporalClient, workflow_id: str):
    handle = temporal.get_workflow_handle(workflow_id)
    await handle.cancel()


def delete_data_import_folder(folder_path: str):
    s3 = s3fs.S3FileSystem(
        key=settings.AIRBYTE_BUCKET_KEY,
        secret=settings.AIRBYTE_BUCKET_SECRET,
    )
    bucket_name = settings.BUCKET_URL
    s3.delete(f"{bucket_name}/{folder_path}", recursive=True)


def is_any_external_data_job_paused(team_id: int) -> bool:
    return ExternalDataSource.objects.filter(team_id=team_id, status=ExternalDataSource.Status.PAUSED).exists()
