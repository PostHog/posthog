import asyncio
import datetime as dt

import pytest
import unittest.mock

from django.test import override_settings

from asgiref.sync import sync_to_async
from flaky import flaky

from posthog.batch_exports.service import disable_and_delete_export, sync_batch_export
from posthog.models import BatchExport, BatchExportDestination, BatchExportRun, Organization, Team

from products.batch_exports.backend.temporal.batch_exports import (
    FinishBatchExportRunInputs,
    OverBillingLimitError,
    StartBatchExportRunInputs,
    finish_batch_export_run,
    start_batch_export_run,
)


@pytest.fixture
def organization():
    """Fixture providing an Organization for testing."""
    org = Organization.objects.create(name="test-org")
    org.save()

    yield org

    org.delete()


@pytest.fixture
def team(organization):
    """Fixture providing a Team for testing."""
    team = Team.objects.create(organization=organization)
    team.save()

    yield team

    team.delete()


@pytest.fixture
def destination(team):
    """Fixture providing an BatchExportDestination for testing."""
    dest = BatchExportDestination.objects.create(
        type="S3",
        config={
            "bucket_name": "bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "aws_access_key_id": "key_id",
            "aws_secret_access_key": "secret",
        },
    )
    dest.save()

    yield dest

    dest.delete()


@pytest.fixture
def batch_export(destination, team):
    """A test BatchExport."""
    batch_export = BatchExport.objects.create(
        name="test export", team=team, destination=destination, interval="hour", paused=False
    )

    batch_export.save()

    sync_batch_export(batch_export, created=True)

    yield batch_export

    disable_and_delete_export(batch_export)
    batch_export.delete()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_start_batch_export_run(activity_environment, team, batch_export):
    """Test the 'start_batch_export_run' activity.

    We check if a 'BatchExportRun' is created after the activity runs.
    """
    start = dt.datetime(2023, 4, 24, tzinfo=dt.UTC)
    end = dt.datetime(2023, 4, 25, tzinfo=dt.UTC)

    inputs = StartBatchExportRunInputs(
        team_id=team.id,
        batch_export_id=str(batch_export.id),
        data_interval_start=start.isoformat(),
        data_interval_end=end.isoformat(),
    )

    run_id = await activity_environment.run(start_batch_export_run, inputs)

    runs = BatchExportRun.objects.filter(id=run_id)
    assert await sync_to_async(runs.exists)()

    run = await sync_to_async(runs.first)()
    assert run is not None
    assert run.data_interval_start == start
    assert run.data_interval_end == end


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_start_batch_export_run_raises_on_mocked_over_limit(activity_environment, team, batch_export):
    """Test the 'start_batch_export_run' activity raises an exception."""
    start = dt.datetime(2023, 4, 24, tzinfo=dt.UTC)
    end = dt.datetime(2023, 4, 25, tzinfo=dt.UTC)

    with override_settings(BATCH_EXPORTS_ENABLE_BILLING_CHECK=True):
        inputs = StartBatchExportRunInputs(
            team_id=team.id,
            batch_export_id=str(batch_export.id),
            data_interval_start=start.isoformat(),
            data_interval_end=end.isoformat(),
        )

    fut: asyncio.Future[bool] = asyncio.Future()
    fut.set_result(False)

    with (
        unittest.mock.patch(
            "products.batch_exports.backend.temporal.batch_exports.check_is_over_limit", return_value=fut
        ),
        pytest.raises(OverBillingLimitError),
    ):
        _ = await activity_environment.run(start_batch_export_run, inputs)

    runs = BatchExportRun.objects.filter(batch_export=batch_export)
    assert await sync_to_async(runs.exists)()

    run = await sync_to_async(runs.first)()
    assert run is not None
    assert run.data_interval_start == start
    assert run.data_interval_end == end
    assert run.status == BatchExportRun.Status.FAILED_BILLING


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_start_batch_export_run_does_not_check_billing_limit(activity_environment, team, batch_export):
    """Test the 'start_batch_export_run' doesn't check billing limit when disabled.

    There are two ways to disable billing check:
    * With the `BATCH_EXPORTS_ENABLE_BILLING_CHECK` setting disabled.
    * By passing `False` to the `check_billing` argument.

    So, we check both.
    """
    start = dt.datetime(2023, 4, 24, tzinfo=dt.UTC)
    end = dt.datetime(2023, 4, 25, tzinfo=dt.UTC)

    with override_settings(BATCH_EXPORTS_ENABLE_BILLING_CHECK=False):
        inputs_with_default = StartBatchExportRunInputs(
            team_id=team.id,
            batch_export_id=str(batch_export.id),
            data_interval_start=start.isoformat(),
            data_interval_end=end.isoformat(),
        )
    inputs_set = StartBatchExportRunInputs(
        team_id=team.id,
        batch_export_id=str(batch_export.id),
        data_interval_start=start.isoformat(),
        data_interval_end=end.isoformat(),
        check_billing=False,
    )
    fut: asyncio.Future[bool] = asyncio.Future()
    fut.set_result(False)

    for inputs in (inputs_with_default, inputs_set):
        with unittest.mock.patch(
            "products.batch_exports.backend.temporal.batch_exports.check_is_over_limit", return_value=fut
        ) as mocked:
            run_id = await activity_environment.run(start_batch_export_run, inputs)

            mocked.assert_not_called()

        runs = BatchExportRun.objects.filter(batch_export=batch_export)
        run = await sync_to_async(runs.get)(id=run_id)
        assert run is not None
        assert run.data_interval_start == start
        assert run.data_interval_end == end
        assert run.status == BatchExportRun.Status.STARTING


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_finish_batch_export_run(activity_environment, team, batch_export):
    """Test the export_run_status activity."""
    start = dt.datetime(2023, 4, 24, tzinfo=dt.UTC)
    end = dt.datetime(2023, 4, 25, tzinfo=dt.UTC)

    inputs = StartBatchExportRunInputs(
        team_id=team.id,
        batch_export_id=str(batch_export.id),
        data_interval_start=start.isoformat(),
        data_interval_end=end.isoformat(),
    )

    run_id = await activity_environment.run(start_batch_export_run, inputs)

    runs = BatchExportRun.objects.filter(id=run_id)
    run = await sync_to_async(runs.first)()
    assert run is not None
    assert run.status == "Starting"

    finish_inputs = FinishBatchExportRunInputs(
        id=str(run_id),
        batch_export_id=str(batch_export.id),
        status="Completed",
        team_id=inputs.team_id,
    )
    await activity_environment.run(finish_batch_export_run, finish_inputs)

    runs = BatchExportRun.objects.filter(id=run_id)
    run = await sync_to_async(runs.first)()
    assert run is not None
    assert run.status == "Completed"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_finish_batch_export_run_pauses_if_reaching_failure_threshold(activity_environment, team, batch_export):
    """Test if 'finish_batch_export_run' will pause a batch export upon reaching failure_threshold."""
    start = dt.datetime(2023, 4, 24, tzinfo=dt.UTC)
    end = dt.datetime(2023, 4, 25, tzinfo=dt.UTC)

    inputs = StartBatchExportRunInputs(
        team_id=team.id,
        batch_export_id=str(batch_export.id),
        data_interval_start=start.isoformat(),
        data_interval_end=end.isoformat(),
    )

    batch_export_id = str(batch_export.id)
    failure_threshold = 10

    for run_number in range(1, failure_threshold * 2):
        run_id = await activity_environment.run(start_batch_export_run, inputs)

        finish_inputs = FinishBatchExportRunInputs(
            id=str(run_id),
            batch_export_id=batch_export_id,
            status=BatchExportRun.Status.FAILED,
            team_id=inputs.team_id,
            latest_error="Oh No!",
            failure_threshold=failure_threshold,
        )

        await activity_environment.run(finish_batch_export_run, finish_inputs)
        await sync_to_async(batch_export.refresh_from_db)()

        if run_number >= failure_threshold:
            assert batch_export.paused is True
        else:
            assert batch_export.paused is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_finish_batch_export_run_never_pauses_with_small_check_window(activity_environment, team, batch_export):
    """Test if 'finish_batch_export_run' will never pause a batch export with a small check window."""
    start = dt.datetime(2023, 4, 24, tzinfo=dt.UTC)
    end = dt.datetime(2023, 4, 25, tzinfo=dt.UTC)

    inputs = StartBatchExportRunInputs(
        team_id=team.id,
        batch_export_id=str(batch_export.id),
        data_interval_start=start.isoformat(),
        data_interval_end=end.isoformat(),
    )

    batch_export_id = str(batch_export.id)
    failure_threshold = 1

    run_id = await activity_environment.run(start_batch_export_run, inputs)

    finish_inputs = FinishBatchExportRunInputs(
        id=str(run_id),
        batch_export_id=batch_export_id,
        status=BatchExportRun.Status.FAILED,
        team_id=inputs.team_id,
        latest_error="Oh No!",
        failure_threshold=failure_threshold,
        failure_check_window=failure_threshold - 1,
    )

    with pytest.raises(ValueError):
        await activity_environment.run(finish_batch_export_run, finish_inputs)

    await sync_to_async(batch_export.refresh_from_db)()

    assert batch_export.paused is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@flaky(max_runs=3, min_passes=1)
async def test_finish_batch_export_run_handles_nul_bytes(activity_environment, team, batch_export):
    """Test if 'finish_batch_export_run' will not fail in the prescence of a NUL byte."""
    start = dt.datetime(2023, 4, 24, tzinfo=dt.UTC)
    end = dt.datetime(2023, 4, 25, tzinfo=dt.UTC)

    inputs = StartBatchExportRunInputs(
        team_id=team.id,
        batch_export_id=str(batch_export.id),
        data_interval_start=start.isoformat(),
        data_interval_end=end.isoformat(),
    )

    batch_export_id = str(batch_export.id)

    run_id = await activity_environment.run(start_batch_export_run, inputs)

    finish_inputs = FinishBatchExportRunInputs(
        id=str(run_id),
        batch_export_id=batch_export_id,
        status=BatchExportRun.Status.FAILED,
        team_id=inputs.team_id,
        latest_error="Oh No a NUL byte: \x00!",
    )

    await activity_environment.run(finish_batch_export_run, finish_inputs)

    runs = BatchExportRun.objects.filter(id=run_id)
    run = await sync_to_async(runs.first)()
    assert run is not None
    assert run.status == "Failed"
    assert run.latest_error == "Oh No a NUL byte: !"
