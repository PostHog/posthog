import uuid

import pytest_asyncio

from posthog.batch_exports.models import BatchExport, BatchExportBackfill, BatchExportDestination, BatchExportRun
from posthog.batch_exports.service import acreate_batch_export_backfill


@pytest_asyncio.fixture
async def batch_export(ateam):
    destination = await BatchExportDestination.objects.acreate(
        type="S3",
        config={
            "bucket_name": "test",
            "region": "us-east-1",
            "prefix": "test",
            "aws_access_key_id": "test",
            "aws_secret_access_key": "test",
        },
    )
    batch_export = await BatchExport.objects.acreate(
        team=ateam,
        destination=destination,
        interval="hour",
        name="Test Export",
    )
    yield batch_export
    await batch_export.adelete()


async def test_creates_new_backfill(ateam, batch_export):
    backfill = await acreate_batch_export_backfill(
        batch_export_id=batch_export.id,
        team_id=ateam.id,
        start_at="2024-01-01T00:00:00+00:00",
        end_at="2024-01-02T00:00:00+00:00",
    )

    assert backfill.batch_export_id == batch_export.id
    assert backfill.team_id == ateam.id
    assert backfill.status == BatchExportRun.Status.RUNNING
    assert await BatchExportBackfill.objects.filter(id=backfill.id).aexists()


async def test_creates_new_backfill_with_preset_id(ateam, batch_export):
    backfill_id = str(uuid.uuid4())
    backfill = await acreate_batch_export_backfill(
        batch_export_id=batch_export.id,
        team_id=ateam.id,
        start_at="2024-01-01T00:00:00+00:00",
        end_at="2024-01-02T00:00:00+00:00",
        backfill_id=backfill_id,
    )

    assert str(backfill.id) == backfill_id


async def test_returns_existing_backfill_on_retry_with_same_id(ateam, batch_export):
    backfill_id = str(uuid.uuid4())
    kwargs = {
        "batch_export_id": batch_export.id,
        "team_id": ateam.id,
        "start_at": "2024-01-01T00:00:00+00:00",
        "end_at": "2024-01-02T00:00:00+00:00",
        "backfill_id": backfill_id,
    }

    first = await acreate_batch_export_backfill(**kwargs)
    second = await acreate_batch_export_backfill(**kwargs)

    assert str(first.id) == str(second.id)
    assert await BatchExportBackfill.objects.filter(id=backfill_id).acount() == 1


async def test_creates_backfill_without_id_does_not_deduplicate(ateam, batch_export):
    kwargs = {
        "batch_export_id": batch_export.id,
        "team_id": ateam.id,
        "start_at": "2024-01-01T00:00:00+00:00",
        "end_at": "2024-01-02T00:00:00+00:00",
    }

    first = await acreate_batch_export_backfill(**kwargs)
    second = await acreate_batch_export_backfill(**kwargs)

    assert first.id != second.id
