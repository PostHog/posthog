import uuid
import datetime as dt

import pytest

from django.conf import settings

from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.service import BatchExportModel
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export, afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.destinations.workflows_batch_export import (
    WorkflowsBatchExportInputs,
    WorkflowsBatchExportWorkflow,
    insert_into_kafka_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.tests.temporal.destinations.workflows.utils import (
    assert_clickhouse_records_in_kafka,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
]


@pytest.fixture
async def workflows_batch_export(ateam, interval, exclude_events, temporal_client, topic, security_protocol, hosts):
    destination_data = {
        "type": "Workflows",
        "config": {"topic": topic},
    }
    batch_export_data = {
        "name": "my-production-workflows-export",
        "destination": destination_data,
        "interval": interval,
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
async def test_workflows_export_workflow(
    clickhouse_client,
    workflows_batch_export,
    ateam,
    interval,
    exclude_events,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    hosts,
    topic,
    security_protocol,
):
    """Test Workflows Export Workflow end-to-end.

    The workflow should update the batch export run status to completed and produce the expected
    records to the Kafka topic.
    """
    model = BatchExportModel(name="events", schema=None)

    workflow_id = str(uuid.uuid4())
    inputs = WorkflowsBatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(workflows_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=model,
        exclude_events=exclude_events,
        **workflows_batch_export.destination.config,
    )
    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[WorkflowsBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_internal_stage_activity,
                insert_into_kafka_activity_from_stage,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                WorkflowsBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=20),
            )

    runs = await afetch_batch_export_runs(batch_export_id=workflows_batch_export.id)
    assert len(runs) == 1

    events_to_export_created, _ = generate_test_data

    run = runs[0]
    assert run.status == "Completed"
    assert run.records_completed == len(events_to_export_created)

    await assert_clickhouse_records_in_kafka(
        clickhouse_client=clickhouse_client,
        topic=topic,
        date_ranges=[(data_interval_start, data_interval_end)],
        team_id=ateam.pk,
        batch_export_model=model,
        exclude_events=exclude_events,
        sort_key="event",
        batch_export_id=str(workflows_batch_export.id),
    )
