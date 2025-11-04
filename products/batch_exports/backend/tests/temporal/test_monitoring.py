import uuid
import datetime as dt

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from django.conf import settings

from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import afetch_batch_export_runs_in_range
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export, afetch_batch_export_runs

from products.batch_exports.backend.temporal.monitoring import (
    BatchExportMonitoringInputs,
    BatchExportMonitoringWorkflow,
    EventCount,
    _log_warning_for_missing_batch_export_runs,
    _log_warning_for_missing_events,
    datetime_to_str,
    fetch_exported_event_counts,
    get_batch_export,
    get_clickhouse_event_counts,
    reconcile_event_counts,
    update_batch_export_runs,
)
from products.batch_exports.backend.tests.temporal.utils.clickhouse import (
    create_clickhouse_tables_and_views,
    truncate_events,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

NOW = dt.datetime.now(tz=dt.UTC)
GENERATE_TEST_DATA_END = NOW.replace(minute=0, second=0, microsecond=0, tzinfo=dt.UTC) - dt.timedelta(hours=1)
GENERATE_TEST_DATA_START = GENERATE_TEST_DATA_END - dt.timedelta(hours=1)


@pytest.fixture(scope="module", autouse=True)
async def clickhouse_db_setup(clickhouse_client):
    await create_clickhouse_tables_and_views(clickhouse_client)


@pytest.fixture(autouse=True)
async def truncate(clickhouse_client):
    """Fixture to automatically truncate sharded_events after a test."""
    yield
    await truncate_events(clickhouse_client)


@pytest.fixture
async def batch_export(ateam, temporal_client):
    """Provide a batch export for tests, not intended to be used."""
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "a-bucket",
            "region": "us-east-1",
            "prefix": "a-key",
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "every 5 minutes",
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],  # type: ignore
        destination_data=batch_export_data["destination"],  # type: ignore
        interval=batch_export_data["interval"],  # type: ignore
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


@pytest.fixture
async def generate_batch_export_runs(
    generate_test_data,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    interval: str,
    batch_export,
):
    # to keep things simple for now, we assume 5 min interval
    if interval != "every 5 minutes":
        raise NotImplementedError("Only 5 minute intervals are supported for now. Please update the test.")

    events_created, _ = generate_test_data

    batch_export_runs: list[BatchExportRun] = []
    interval_start = data_interval_start
    interval_end = interval_start + dt.timedelta(minutes=5)
    while interval_end <= data_interval_end:
        run = BatchExportRun(
            batch_export_id=batch_export.id,
            data_interval_start=interval_start,
            data_interval_end=interval_end,
            status="completed",
            records_completed=len(
                [
                    e
                    for e in events_created
                    if interval_start
                    <= dt.datetime.fromisoformat(e["inserted_at"]).replace(tzinfo=dt.UTC)
                    < interval_end
                ]
            ),
        )
        await run.asave()
        batch_export_runs.append(run)
        interval_start = interval_end
        interval_end += dt.timedelta(minutes=5)

    yield

    for run in batch_export_runs:
        await run.adelete()


async def _run_workflow(batch_export):
    workflow_id = str(uuid.uuid4())
    inputs = BatchExportMonitoringInputs(batch_export_id=batch_export.id)
    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[BatchExportMonitoringWorkflow],
            activities=[
                get_batch_export,
                get_clickhouse_event_counts,
                fetch_exported_event_counts,
                update_batch_export_runs,
                reconcile_event_counts,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            batch_export_runs_updated = await activity_environment.client.execute_workflow(
                BatchExportMonitoringWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=30),
            )
            return batch_export_runs_updated


async def test_monitoring_workflow_when_no_event_data(batch_export):
    batch_export_runs_updated = await _run_workflow(batch_export)
    assert batch_export_runs_updated == 0


@pytest.mark.parametrize(
    "data_interval_start",
    [GENERATE_TEST_DATA_START],
    indirect=True,
)
@pytest.mark.parametrize(
    "data_interval_end",
    [GENERATE_TEST_DATA_END],
    indirect=True,
)
@pytest.mark.parametrize(
    "interval",
    ["every 5 minutes"],
    indirect=True,
)
@freeze_time(NOW)
async def test_monitoring_workflow_no_issues(
    batch_export,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    interval,
    generate_batch_export_runs,
):
    """Test the monitoring workflow with a batch export that has data.

    We generate some dummy batch export runs based on the event data we
    generated and assert that the expected records count matches the records
    completed.
    """

    with (
        patch(
            "products.batch_exports.backend.temporal.monitoring._log_warning_for_missing_batch_export_runs"
        ) as mock_log_warning,
        patch(
            "products.batch_exports.backend.temporal.monitoring._log_warning_for_missing_events"
        ) as mock_log_warning_missing_events,
    ):
        await _run_workflow(batch_export)

        # check that no warnings were logged
        mock_log_warning.assert_not_called()
        mock_log_warning_missing_events.assert_not_called()

        # check that the batch export runs were updated correctly
        batch_export_runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)

        for run in batch_export_runs:
            if run.records_completed == 0:
                # TODO: in the actual monitoring activity it would be better to
                # update the actual count to 0 rather than None
                assert run.records_total_count is None
            else:
                assert run.records_completed == run.records_total_count


@pytest.mark.parametrize(
    "data_interval_start",
    [GENERATE_TEST_DATA_START],
    indirect=True,
)
@pytest.mark.parametrize(
    "data_interval_end",
    [GENERATE_TEST_DATA_END],
    indirect=True,
)
@pytest.mark.parametrize(
    "interval",
    ["every 5 minutes"],
    indirect=True,
)
@freeze_time(NOW)
async def test_monitoring_workflow_when_missing_batch_export_runs(
    batch_export,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    interval,
    generate_batch_export_runs,
):
    """Test the monitoring workflow with a batch export that has missing batch export runs.

    We simulate a missing batch export run by deleting the batch export run for the first 5 minutes.
    """

    expected_missing_runs: list[tuple[dt.datetime, dt.datetime]] = []
    # simulate a missing batch export run by deleting the batch export run for the first 5 minutes
    runs: list[BatchExportRun] = await afetch_batch_export_runs_in_range(
        batch_export_id=batch_export.id,
        interval_start=data_interval_start,
        interval_end=data_interval_start + dt.timedelta(minutes=5),
    )
    assert len(runs) == 1
    for run in runs:
        assert run.data_interval_start is not None
        expected_missing_runs.append((run.data_interval_start, run.data_interval_end))
        await run.adelete()

    with patch(
        "products.batch_exports.backend.temporal.monitoring._log_warning_for_missing_batch_export_runs"
    ) as mock_log_warning:
        await _run_workflow(batch_export)

        # check that the warning was logged
        mock_log_warning.assert_called_once_with(batch_export.id, expected_missing_runs)

        # check that the batch export runs were updated correctly
        batch_export_runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)

        for run in batch_export_runs:
            if run.records_completed == 0:
                # TODO: in the actual monitoring activity it would be better to
                # update the actual count to 0 rather than None
                assert run.records_total_count is None
            else:
                assert run.records_completed == run.records_total_count


@pytest.mark.parametrize(
    "data_interval_start",
    [GENERATE_TEST_DATA_START],
    indirect=True,
)
@pytest.mark.parametrize(
    "data_interval_end",
    [GENERATE_TEST_DATA_END],
    indirect=True,
)
@pytest.mark.parametrize(
    "interval",
    ["every 5 minutes"],
    indirect=True,
)
@freeze_time(NOW)
async def test_monitoring_workflow_when_missing_events(
    batch_export,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    interval,
    generate_batch_export_runs,
):
    """Test the monitoring workflow with a batch export that has missing exported events."""

    # simulate missing exported events by adjusting the records_completed
    expected_missing_events: list[EventCount] = []
    runs: list[BatchExportRun] = await afetch_batch_export_runs_in_range(
        batch_export_id=batch_export.id,
        interval_start=data_interval_start,
        interval_end=data_interval_end,
    )
    assert len(runs) > 0
    for run in runs:
        if run.records_completed and run.records_completed > 1:
            assert run.data_interval_start is not None
            missing_events = run.records_completed // 2
            expected_missing_events.append(
                EventCount(
                    interval_start=datetime_to_str(run.data_interval_start),
                    interval_end=datetime_to_str(run.data_interval_end),
                    count=missing_events,
                )
            )
            run.records_completed -= missing_events
            await run.asave()

    with patch(
        "products.batch_exports.backend.temporal.monitoring._log_warning_for_missing_events"
    ) as mock_log_warning:
        await _run_workflow(batch_export)

        # check that the warning was logged
        mock_log_warning.assert_called_once_with(batch_export.id, expected_missing_events)


def test_log_warning_for_missing_batch_export_runs():
    missing_runs = [
        (dt.datetime(2024, 1, 1, 10, 0), dt.datetime(2024, 1, 1, 10, 5)),
        (dt.datetime(2024, 1, 1, 10, 5), dt.datetime(2024, 1, 1, 10, 10)),
    ]
    with patch("products.batch_exports.backend.temporal.monitoring.LOGGER") as mock_global_logger:
        mock_logger = MagicMock()
        mock_global_logger.bind.return_value = mock_logger

        batch_export_id = uuid.uuid4()
        _log_warning_for_missing_batch_export_runs(batch_export_id, missing_runs)

        mock_logger.warning.assert_called_once_with(
            "Batch Exports Monitoring: Found 2 missing run(s):\n"
            "- Run 2024-01-01 10:00:00 to 2024-01-01 10:05:00\n"
            "- Run 2024-01-01 10:05:00 to 2024-01-01 10:10:00\n"
        )


def test_log_warning_for_missing_events():
    missing_events = [
        EventCount(interval_start="2024-01-01 10:00:00", interval_end="2024-01-01 10:05:00", count=100),
        EventCount(interval_start="2024-01-01 10:05:00", interval_end="2024-01-01 10:10:00", count=200),
    ]
    with patch("products.batch_exports.backend.temporal.monitoring.LOGGER") as mock_global_logger:
        mock_logger = MagicMock()
        mock_global_logger.bind.return_value = mock_logger

        batch_export_id = uuid.uuid4()
        _log_warning_for_missing_events(batch_export_id, missing_events)

        mock_logger.warning.assert_called_once_with(
            f"Batch Exports Monitoring: Found missing events:\n"
            "- 100 events missing in interval 2024-01-01 10:00:00 to 2024-01-01 10:05:00\n"
            "- 200 events missing in interval 2024-01-01 10:05:00 to 2024-01-01 10:10:00\n"
        )
