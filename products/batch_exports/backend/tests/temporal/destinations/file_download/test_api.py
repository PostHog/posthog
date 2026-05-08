import time
import uuid
import asyncio
import datetime as dt
from urllib.parse import urlsplit

import pytest
import freezegun

from django.conf import settings
from django.test import AsyncClient, override_settings

import aiohttp
import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import sync_to_async
from rest_framework import status
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.api.file_download import (
    _calculate_expiration_for_file_download,
    _generate_s3_pre_signed_url,
    _get_file_download_for_run,
)
from posthog.models import BatchExportDestination, BatchExportFileDownload, BatchExportOnDemand, BatchExportRun

from products.batch_exports.backend.temporal import ACTIVITIES, WORKFLOWS

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
]


async def test_can_generate_s3_pre_signed_url(s3_client, s3_bucket, aws_role_arn):
    """Test we can generate a S3 pre signed URL for some test data."""
    key = f"batch-exports/{str(uuid.uuid4())}"
    test_data = b"test-data"
    await s3_client.put_object(Bucket=s3_bucket, Key=key, Body=test_data)

    url = _generate_s3_pre_signed_url(
        s3_bucket, key, role_arn=aws_role_arn, session_name="unit-test", max_attempts=10, delay=2
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            result = await response.read()

    assert result == test_data


@pytest.mark.django_db(transaction=True)
async def test_get_file_download_for_run(team, data_interval_start, data_interval_end):
    destination = await BatchExportDestination.objects.acreate(
        type=BatchExportDestination.Destination.FILE_DOWNLOAD, config={}
    )
    batch_export = await BatchExportOnDemand.objects.acreate(team=team, destination=destination, model="events")
    run = await BatchExportRun.objects.acreate(
        batch_export_on_demand=batch_export,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        status=BatchExportRun.Status.COMPLETED,
    )
    file_downloads = []
    for index in range(5):
        file_download = await BatchExportFileDownload.objects.acreate(
            team=team,
            batch_export_run=run,
            key=f"batch-exports/{index}",
        )
        file_downloads.append(file_download)

    no_part_file = await sync_to_async(_get_file_download_for_run)(run)
    index_first_file = await sync_to_async(_get_file_download_for_run)(run, 0)
    id_first_file = await sync_to_async(_get_file_download_for_run)(run, str(file_downloads[0].id))

    assert no_part_file == index_first_file == id_first_file == file_downloads[0]

    for index, file_download in enumerate(file_downloads[1:], start=1):
        index_file = await sync_to_async(_get_file_download_for_run)(run, index)
        id_file = await sync_to_async(_get_file_download_for_run)(run, str(file_download.id))

        assert index_file == id_file == file_downloads[index]


@freezegun.freeze_time()
async def test_calculate_expiration_for_file_download(ateam):
    """Test calculating the expiration time given a file download."""
    destination = BatchExportDestination(type=BatchExportDestination.Destination.FILE_DOWNLOAD, config={})
    batch_export = BatchExportOnDemand(team_id=ateam.pk, destination=destination, model="events")

    now = dt.datetime.now(dt.UTC)
    batch_export_run = BatchExportRun(
        status=BatchExportRun.Status.STARTING,
        batch_export_on_demand=batch_export,
        data_interval_start=now - dt.timedelta(days=1),
        data_interval_end=now,
    )

    expected = dt.timedelta(hours=24)
    file_download = BatchExportFileDownload(
        team_id=ateam.pk, batch_export_run=batch_export_run, expires_at=now + expected
    )

    default_expiration = expected + dt.timedelta(seconds=1)
    expiration = _calculate_expiration_for_file_download(file_download, default_expiration=dt.timedelta(hours=25))

    assert expiration == expected

    default_expiration = expected - dt.timedelta(seconds=1)
    expiration = _calculate_expiration_for_file_download(file_download, default_expiration=default_expiration)

    assert expiration == default_expiration


@pytest.fixture
def team(base_test_mixin_fixture):
    return base_test_mixin_fixture.team


@pytest.fixture
def ateam(team):
    """Override the async-team fixture to use login-capable team.

    This is used by `generate_test_data`, so it needs to be the same team so that data
    is generated correctly.
    """
    return team


@pytest.fixture
def override_file_download_settings(aws_role_arn, s3_bucket):
    with override_settings(
        BATCH_EXPORTS_FILE_DOWNLOAD_ROLE_ARN=aws_role_arn,
        BATCH_EXPORTS_FILE_DOWNLOAD_BUCKET=s3_bucket,
        BATCH_EXPORTS_FILE_DOWNLOAD_EXPIRATION_SECONDS=900,  # Minimum
    ):
        yield


@pytest.mark.django_db(transaction=True)
async def test_file_download_retrieve_returns_error(
    async_client: AsyncClient, temporal_client, team, user, data_interval_start, data_interval_end, generate_test_data
):
    destination = await BatchExportDestination.objects.acreate(
        type=BatchExportDestination.Destination.FILE_DOWNLOAD, config={}
    )
    batch_export = await BatchExportOnDemand.objects.acreate(team=team, destination=destination, model="events")
    run = await BatchExportRun.objects.acreate(
        batch_export_on_demand=batch_export,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        status=BatchExportRun.Status.FAILED,
        latest_error="some error message",
    )

    await async_client.aforce_login(user)

    status_response = await async_client.get(
        f"/api/projects/{team.pk}/file_download_batch_exports/{run.id}",
    )
    data = status_response.json()
    assert data["status"] == "Failed", status_response.json()
    assert data.get("error", None) is not None
    assert data["error"] == "some error message"


@pytest.mark.django_db(transaction=True)
async def test_file_download_retrieve_returns_files(
    async_client: AsyncClient,
    temporal_client,
    team,
    user,
    data_interval_start,
    data_interval_end,
):
    destination = await BatchExportDestination.objects.acreate(
        type=BatchExportDestination.Destination.FILE_DOWNLOAD, config={}
    )
    batch_export = await BatchExportOnDemand.objects.acreate(team=team, destination=destination, model="events")
    run = await BatchExportRun.objects.acreate(
        batch_export_on_demand=batch_export,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        status=BatchExportRun.Status.COMPLETED,
    )

    file_downloads = []
    for index in range(5):
        file_download = await BatchExportFileDownload.objects.acreate(
            team=team,
            batch_export_run=run,
            key=f"batch-exports/{index}",
        )
        file_downloads.append(file_download)

    await async_client.aforce_login(user)

    status_response = await async_client.get(
        f"/api/projects/{team.pk}/file_download_batch_exports/{run.id}",
    )
    data = status_response.json()
    assert data["status"] == "Completed", status_response.json()
    assert data["files"] == [str(file_download.id) for file_download in file_downloads]


@pytest.mark.usefixtures("override_file_download_settings")
@pytest.mark.django_db(transaction=True)
async def test_file_download_download_fails_when_not_completed(
    async_client: AsyncClient, temporal_client, team, user, data_interval_start, data_interval_end, generate_test_data
):
    destination = await BatchExportDestination.objects.acreate(
        type=BatchExportDestination.Destination.FILE_DOWNLOAD, config={}
    )
    batch_export = await BatchExportOnDemand.objects.acreate(team=team, destination=destination, model="events")

    await async_client.aforce_login(user)

    for run_status in (BatchExportRun.Status.RUNNING, BatchExportRun.Status.STARTING, BatchExportRun.Status.FAILED):
        run = await BatchExportRun.objects.acreate(
            batch_export_on_demand=batch_export,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            status=run_status,
        )

        response = await async_client.get(
            f"/api/projects/{team.pk}/file_download_batch_exports/{run.id}/download",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        if run_status == BatchExportRun.Status.FAILED:
            assert b"has failed" in response.content
        else:
            assert b"still in progress" in response.content


@pytest.mark.usefixtures("override_file_download_settings")
@pytest.mark.django_db(transaction=True)
async def test_file_download_download(
    async_client: AsyncClient, temporal_client, team, user, data_interval_start, data_interval_end, generate_test_data
):
    destination = await BatchExportDestination.objects.acreate(
        type=BatchExportDestination.Destination.FILE_DOWNLOAD, config={}
    )
    batch_export = await BatchExportOnDemand.objects.acreate(team=team, destination=destination, model="events")
    run = await BatchExportRun.objects.acreate(
        batch_export_on_demand=batch_export,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        status=BatchExportRun.Status.COMPLETED,
    )
    file_downloads = []
    for index in range(5):
        file_download = await BatchExportFileDownload.objects.acreate(
            team=team,
            batch_export_run=run,
            key=f"batch-exports/{index}",
        )
        file_downloads.append(file_download)

    await async_client.aforce_login(user)

    # The first file is special as it should also be the one returned when no part is
    # passed.
    response = await async_client.get(
        f"/api/projects/{team.pk}/file_download_batch_exports/{run.id}/download",
    )
    no_part_pre_signed_url = urlsplit(response["Location"])

    first_file = file_downloads[0]
    response = await async_client.get(
        f"/api/projects/{team.pk}/file_download_batch_exports/{run.id}/download/{first_file.id}",
    )
    first_file_pre_signed_url = urlsplit(response["Location"])

    response = await async_client.get(
        f"/api/projects/{team.pk}/file_download_batch_exports/{run.id}/download/0",
    )
    first_index_pre_signed_url = urlsplit(response["Location"])

    # URLs won't be exactly the same as the signature is newly generated on each
    # request, but the path to the file should be the same.
    assert (
        "/batch-exports/0"
        == f"/{first_file.key}"
        == first_index_pre_signed_url.path
        == first_file_pre_signed_url.path
        == no_part_pre_signed_url.path
    )

    for index, file_download in enumerate(file_downloads[1:], start=1):
        response = await async_client.get(
            f"/api/projects/{team.pk}/file_download_batch_exports/{run.id}/download/{file_download.id}",
        )
        file_pre_signed_url = urlsplit(response["Location"])

        response = await async_client.get(
            f"/api/projects/{team.pk}/file_download_batch_exports/{run.id}/download/{index}",
        )
        index_pre_signed_url = urlsplit(response["Location"])

        assert (
            f"/batch-exports/{index}"
            == f"/{file_download.key}"
            == file_pre_signed_url.path
            == index_pre_signed_url.path
        )


@pytest.mark.usefixtures("override_file_download_settings")
@pytest.mark.django_db(transaction=True)
async def test_file_download_end_to_end(
    async_client: AsyncClient, temporal_client, team, user, data_interval_start, data_interval_end, generate_test_data
):
    await async_client.aforce_login(user)

    async with Worker(
        temporal_client,
        task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        response = await async_client.post(
            f"/api/projects/{team.pk}/file_download_batch_exports",
            {
                "file": {
                    "format": "Parquet",
                    "compression": "zstd",
                },
                "model": "events",
                "data_interval_start": data_interval_start,
                "data_interval_end": data_interval_end,
            },
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()

        data = response.json()
        run_id = data["id"]

        timeout = 60
        start = time.monotonic()
        files = None
        while True:
            status_response = await async_client.get(
                f"/api/projects/{team.pk}/file_download_batch_exports/{run_id}",
            )
            data = status_response.json()
            assert data["status"] in ("Starting", "Running", "Completed"), status_response.json()
            assert data.get("error", None) is None

            if data["status"] == "Completed":
                assert "files" in data
                files = data["files"]
                break

            now = time.monotonic()
            if now - start > timeout:
                raise TimeoutError("Batch export run took too long to complete")

            await asyncio.sleep(2)

    assert len(files) == 1
    response = await async_client.get(
        f"/api/projects/{team.pk}/file_download_batch_exports/{run_id}/download/{files[0]}",
    )
    assert response.status_code == 302
    pre_signed_url = response["Location"]

    async with aiohttp.ClientSession() as s:
        async with s.get(pre_signed_url) as resp:
            content = await resp.read()

            assert resp.status == 200, f"Invalid status: {resp.status}: {content!r}"

    table = pq.read_table(pa.BufferReader(content))
    events, _ = generate_test_data

    assert len(table) == len(events)
    assert "event" in table.column_names
