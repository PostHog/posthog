import time
import uuid
import random
import asyncio
import datetime as dt
from urllib.parse import urlsplit

import pytest
import freezegun
import unittest.mock

from django.conf import settings
from django.test import AsyncClient, override_settings

import aiohttp
import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import sync_to_async
from rest_framework import status
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.scoping import team_scope
from posthog.temporal.tests.utils.events import generate_test_events, insert_event_values_in_clickhouse

from products.batch_exports.backend.api.file_download import (
    _calculate_expiration_for_file_download,
    _generate_s3_pre_signed_url,
    _get_file_download_for_run,
)
from products.batch_exports.backend.models.batch_export import (
    BatchExportDestination,
    BatchExportFileDownload,
    BatchExportOnDemand,
    BatchExportRun,
    BatchExportSource,
)
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
    with team_scope(team_id=team.pk, canonical=True):
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


@pytest.fixture
def mock_start_file_download_export():
    """Mock starting the Temporal workflow so create tests don't reach Temporal."""
    with unittest.mock.patch(
        "products.batch_exports.backend.api.file_download.start_file_download_batch_export"
    ) as mock_start:
        yield mock_start


@pytest.mark.django_db(transaction=True)
async def test_file_download_retrieve_returns_error(
    async_client: AsyncClient, temporal_client, team, user, data_interval_start, data_interval_end, generate_test_data
):
    destination = await BatchExportDestination.objects.acreate(
        type=BatchExportDestination.Destination.FILE_DOWNLOAD, config={}
    )
    with team_scope(team_id=team.pk, canonical=True):
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
    with team_scope(team_id=team.pk, canonical=True):
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


@pytest.mark.django_db(transaction=True)
async def test_file_download_retrieve_returns_empty_when_no_data_exported(
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
    with team_scope(team_id=team.pk, canonical=True):
        batch_export = await BatchExportOnDemand.objects.acreate(team=team, destination=destination, model="events")
    run = await BatchExportRun.objects.acreate(
        batch_export_on_demand=batch_export,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        status=BatchExportRun.Status.COMPLETED,
        records_completed=0,
    )

    await async_client.aforce_login(user)

    status_response = await async_client.get(
        f"/api/projects/{team.pk}/file_download_batch_exports/{run.id}",
    )
    data = status_response.json()
    assert data["status"] == "Completed", status_response.json()
    assert data["files"] == []


@pytest.mark.usefixtures("override_file_download_settings")
@pytest.mark.django_db(transaction=True)
async def test_file_download_download_fails_when_not_completed(
    async_client: AsyncClient, temporal_client, team, user, data_interval_start, data_interval_end, generate_test_data
):
    destination = await BatchExportDestination.objects.acreate(
        type=BatchExportDestination.Destination.FILE_DOWNLOAD, config={}
    )
    with team_scope(team_id=team.pk, canonical=True):
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
    with team_scope(team_id=team.pk, canonical=True):
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


@override_settings(BATCH_EXPORT_MAX_CONCURRENT_ON_DEMAND_PER_TEAM=1)
@pytest.mark.django_db(transaction=True)
async def test_file_download_create_rejects_when_concurrency_limit_reached(
    async_client: AsyncClient,
    team,
    user,
    data_interval_start,
    data_interval_end,
    mock_start_file_download_export,
):
    destination = await BatchExportDestination.objects.acreate(
        type=BatchExportDestination.Destination.FILE_DOWNLOAD, config={}
    )
    with team_scope(team_id=team.pk, canonical=True):
        batch_export = await BatchExportOnDemand.objects.acreate(team=team, destination=destination, model="events")
    await BatchExportRun.objects.acreate(
        batch_export_on_demand=batch_export,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        status=BatchExportRun.Status.RUNNING,
    )

    await async_client.aforce_login(user)

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

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS, response.json()
    assert response.json()["code"] == "too_many_concurrent_file_downloads"
    mock_start_file_download_export.assert_not_called()


@pytest.mark.django_db(transaction=True)
async def test_file_download_create_rejects_future_data_interval_end(
    async_client: AsyncClient,
    team,
    user,
    mock_start_file_download_export,
):
    now = dt.datetime.now(dt.UTC)

    await async_client.aforce_login(user)

    data_interval_end_iso = (now + dt.timedelta(hours=1)).isoformat()
    response = await async_client.post(
        f"/api/projects/{team.pk}/file_download_batch_exports",
        {
            "file": {
                "format": "Parquet",
                "compression": "zstd",
            },
            "model": "events",
            "data_interval_start": (now - dt.timedelta(hours=1)).isoformat(),
            "data_interval_end": data_interval_end_iso,
        },
        content_type="application/json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == f"The provided 'data_interval_end' ({data_interval_end_iso}) is in the future"

    mock_start_file_download_export.assert_not_called()
    assert (
        await BatchExportRun.objects.filter(
            batch_export_on_demand__team_id=team.pk,
            batch_export_on_demand__destination__type=BatchExportDestination.Destination.FILE_DOWNLOAD,
        ).acount()
        == 0
    )


@pytest.mark.django_db(transaction=True)
async def test_file_download_list_returns_run_ids_and_statuses(
    async_client: AsyncClient,
    team,
    user,
    data_interval_start,
    data_interval_end,
):
    destination = await BatchExportDestination.objects.acreate(
        type=BatchExportDestination.Destination.FILE_DOWNLOAD, config={}
    )
    with team_scope(team_id=team.pk, canonical=True):
        batch_export = await BatchExportOnDemand.objects.acreate(team=team, destination=destination, model="events")
    running_run = await BatchExportRun.objects.acreate(
        batch_export_on_demand=batch_export,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        status=BatchExportRun.Status.RUNNING,
    )
    completed_run = await BatchExportRun.objects.acreate(
        batch_export_on_demand=batch_export,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        status=BatchExportRun.Status.COMPLETED,
    )

    running_run.created_at = dt.datetime(2026, 1, 1, 1, 1, 0, tzinfo=dt.UTC)
    await running_run.asave(update_fields=["created_at"])
    completed_run.created_at = dt.datetime(2026, 1, 1, 1, 1, 1, tzinfo=dt.UTC)
    await completed_run.asave(update_fields=["created_at"])

    await async_client.aforce_login(user)

    response = await async_client.get(f"/api/projects/{team.pk}/file_download_batch_exports")

    assert response.status_code == status.HTTP_200_OK, response.json()
    data = response.json()
    assert data["count"] == 2
    assert data["results"] == [
        {"id": str(completed_run.id), "status": BatchExportRun.Status.COMPLETED},
        {"id": str(running_run.id), "status": BatchExportRun.Status.RUNNING},
    ]


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


@pytest.mark.django_db(transaction=True)
async def test_file_download_cancel_mocked(
    async_client: AsyncClient,
    team,
    user,
    data_interval_start,
    data_interval_end,
):
    destination = await BatchExportDestination.objects.acreate(
        type=BatchExportDestination.Destination.FILE_DOWNLOAD, config={}
    )
    with team_scope(team_id=team.pk, canonical=True):
        batch_export = await BatchExportOnDemand.objects.acreate(team=team, destination=destination, model="events")
    run = await BatchExportRun.objects.acreate(
        batch_export_on_demand=batch_export,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        status=BatchExportRun.Status.RUNNING,
    )

    await async_client.aforce_login(user)

    mocked_client = unittest.mock.MagicMock()
    mocked_handle = unittest.mock.AsyncMock()
    mocked_client.get_workflow_handle.return_value = mocked_handle

    with unittest.mock.patch("products.batch_exports.backend.api.file_download.sync_connect") as mocked_connect:
        mocked_connect.return_value = mocked_client
        status_response = await async_client.post(
            f"/api/projects/{team.pk}/file_download_batch_exports/{run.id}/cancel",
        )

    mocked_client.get_workflow_handle.assert_called_once_with(workflow_id=run.workflow_id)
    mocked_handle.cancel.assert_called_once()

    data = status_response.json()
    assert data["status"] == "Cancelled", status_response.json()

    await run.arefresh_from_db()
    assert run.status == BatchExportRun.Status.CANCELLED


class TestFileDownloadHogQL:
    """File download batch exports created from a user-defined HogQL query."""

    HOGQL_FLAG_PATCH_TARGET = "products.batch_exports.backend.api.file_download.posthoganalytics.feature_enabled"

    @pytest.fixture
    def enable_hogql_flag(self):
        """Enable the hogql-batch-exports feature flag for the duration of a test."""
        with unittest.mock.patch(self.HOGQL_FLAG_PATCH_TARGET, return_value=True):
            yield

    @pytest.fixture
    async def hogql_export_test_events(self, clickhouse_client, team):
        """Insert events for this and another team directly into the events table.

        A hogql export reads the main (sharded) events table with no interval filter, so
        the test controls exactly which rows exist there: no duplicates, plus another
        team's rows to verify only this team's data is exported.
        """
        timestamp = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
        events = generate_test_events(
            count=10,
            team_id=team.pk,
            possible_datetimes=[timestamp],
            event_name="test-{i}",
            properties={"$browser": "Chrome"},
        )
        events_from_other_team = generate_test_events(
            count=3,
            team_id=team.pk + random.randint(1, 1000),
            possible_datetimes=[timestamp],
            event_name="test-{i}",
            properties={"$browser": "Chrome"},
        )
        await insert_event_values_in_clickhouse(
            client=clickhouse_client, events=events + events_from_other_team, table="sharded_events"
        )
        return events

    @pytest.mark.django_db(transaction=True)
    async def test_rejected_when_flag_disabled(
        self, async_client: AsyncClient, team, user, mock_start_file_download_export
    ):
        await async_client.aforce_login(user)

        with unittest.mock.patch(self.HOGQL_FLAG_PATCH_TARGET, return_value=False) as mock_flag:
            response = await async_client.post(
                f"/api/projects/{team.pk}/file_download_batch_exports",
                {
                    "file": {"format": "Parquet"},
                    "model": "hogql",
                    "hogql_query": "SELECT event AS event FROM events",
                },
                content_type="application/json",
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert mock_flag.call_args[0][0] == "hogql-batch-exports"
        mock_start_file_download_export.assert_not_called()
        assert await sync_to_async(lambda: BatchExportSource.objects.for_team(team.pk).count())() == 0

    @pytest.mark.parametrize(
        "body_overrides,expected_error_fragment",
        [
            pytest.param(
                {"hogql_query": None},
                "'hogql_query' is required when 'model' is 'hogql'",
                id="missing-query",
            ),
            pytest.param(
                {"hogql_query": "this is not hogql"},
                "Failed to parse HogQL query",
                id="unparseable-query",
            ),
            pytest.param(
                {"hogql_query": "SELECT event AS event FROM events WHERE {filters}"},
                "Placeholders are not supported",
                id="placeholder-query",
            ),
            pytest.param(
                {"hogql_query": "SELECT count() FROM events"},
                "must be a field or have an alias",
                id="unaliased-expression-column",
            ),
            pytest.param(
                {"hogql_query": "SELECT x AS x FROM no_such_table"},
                "Invalid HogQL query",
                id="unknown-table",
            ),
            pytest.param(
                {"data_interval_start": "2026-01-01T00:00:00+00:00", "data_interval_end": "2026-01-02T00:00:00+00:00"},
                "not supported when 'model' is 'hogql'",
                id="intervals-with-hogql",
            ),
            pytest.param(
                {"include": ["my-event"]},
                "'include' and 'exclude' are not supported when 'model' is 'hogql'",
                id="include-with-hogql",
            ),
            pytest.param(
                {"model": "events"},
                "'hogql_query' is only supported when 'model' is 'hogql'",
                id="query-with-events-model",
            ),
            pytest.param(
                {"model": "events", "hogql_query": None},
                "'data_interval_start' and 'data_interval_end' are required",
                id="events-model-missing-intervals",
            ),
        ],
    )
    @pytest.mark.usefixtures("enable_hogql_flag")
    @pytest.mark.django_db(transaction=True)
    async def test_rejects_invalid_requests(
        self,
        async_client: AsyncClient,
        team,
        user,
        mock_start_file_download_export,
        body_overrides,
        expected_error_fragment,
    ):
        await async_client.aforce_login(user)

        body: dict = {
            "file": {"format": "Parquet"},
            "model": "hogql",
            "hogql_query": "SELECT event AS event FROM events",
        }
        for key, value in body_overrides.items():
            if value is None:
                body.pop(key, None)
            else:
                body[key] = value

        response = await async_client.post(
            f"/api/projects/{team.pk}/file_download_batch_exports",
            body,
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert expected_error_fragment in response.content.decode()
        mock_start_file_download_export.assert_not_called()
        assert (
            await BatchExportRun.objects.filter(
                batch_export_on_demand__team_id=team.pk,
                batch_export_on_demand__destination__type=BatchExportDestination.Destination.FILE_DOWNLOAD,
            ).acount()
            == 0
        )
        assert await sync_to_async(lambda: BatchExportSource.objects.for_team(team.pk).count())() == 0

    @pytest.mark.usefixtures("enable_hogql_flag")
    @pytest.mark.django_db(transaction=True)
    async def test_create(self, async_client: AsyncClient, team, user, mock_start_file_download_export):
        """A hogql create request stores the query on a source and threads it to the workflow.

        The run's data interval is faked as now/now: hogql exports have no interval, but
        everything downstream formats concrete bounds.
        """
        await async_client.aforce_login(user)
        hogql_query = "SELECT event AS event, distinct_id AS distinct_id FROM events"

        before = dt.datetime.now(dt.UTC)
        response = await async_client.post(
            f"/api/projects/{team.pk}/file_download_batch_exports",
            {
                "file": {"format": "Parquet"},
                "model": "hogql",
                "hogql_query": hogql_query,
            },
            content_type="application/json",
        )
        after = dt.datetime.now(dt.UTC)

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()

        with team_scope(team_id=team.pk, canonical=True):
            run = await BatchExportRun.objects.select_related(
                "batch_export_on_demand__source", "batch_export_on_demand__destination"
            ).aget(id=response.json()["id"])

        assert run.data_interval_start == run.data_interval_end
        assert before <= run.data_interval_end <= after
        on_demand = run.batch_export_on_demand
        assert on_demand is not None
        assert on_demand.model == "hogql"
        assert on_demand.source is not None
        assert on_demand.source.hogql_query == hogql_query
        assert on_demand.source.team_id == team.pk
        assert "include_events" not in on_demand.destination.config

        mock_start_file_download_export.assert_called_once()
        batch_export_model = mock_start_file_download_export.call_args.kwargs["batch_export_model"]
        assert batch_export_model.name == "hogql"
        assert batch_export_model.hogql_query == hogql_query

    @pytest.mark.usefixtures("override_file_download_settings", "enable_hogql_flag")
    @pytest.mark.django_db(transaction=True)
    async def test_end_to_end(self, async_client: AsyncClient, temporal_client, team, user, hogql_export_test_events):
        """A hogql export produces a downloadable file whose contents match the query results."""
        await async_client.aforce_login(user)

        hogql_query = """
        SELECT event AS event, distinct_id AS distinct_id, properties.$browser AS browser
        FROM events
        """

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
                    "file": {"format": "Parquet", "compression": "zstd"},
                    "model": "hogql",
                    "hogql_query": hogql_query,
                },
                content_type="application/json",
            )
            assert response.status_code == status.HTTP_202_ACCEPTED, response.json()

            run_id = response.json()["id"]

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
                    files = data["files"]
                    break

                if time.monotonic() - start > timeout:
                    raise TimeoutError("Batch export run took too long to complete")

                await asyncio.sleep(2)

        assert files is not None and len(files) == 1
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

        assert table.column_names == ["event", "distinct_id", "browser"]
        exported_rows = sorted((row["event"], row["distinct_id"], row["browser"]) for row in table.to_pylist())
        expected_rows = sorted((e["event"], e["distinct_id"], "Chrome") for e in hogql_export_test_events)
        assert exported_rows == expected_rows
