import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterator

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

import pyarrow as pa
from temporalio.testing import ActivityEnvironment

from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    BigQueryClient,
    BigQueryInsertInputs,
    insert_into_bigquery_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.temporal.queue import RecordBatchQueue

pytestmark = [pytest.mark.asyncio, pytest.mark.timeout(30)]


class StagedExport:
    def __init__(self) -> None:
        batch = pa.record_batch({"amount": [1]})
        buffer = pa.BufferOutputStream()
        with pa.ipc.new_stream(buffer, batch.schema) as writer:
            writer.write_batch(batch)
            writer.write_batch(batch)
        self.data = buffer.getvalue().to_pybytes()
        self.reader_tasks: list[asyncio.Task[None]] = []
        self.producer_task: asyncio.Task[None] | None = None
        self.closing = asyncio.Event()
        self.closed = asyncio.Event()
        self.release_cleanup = asyncio.Event()
        self.release_cleanup.set()
        self.s3 = MagicMock()
        self.s3.list_objects_v2 = AsyncMock(return_value={"Contents": [{"Key": "stage/data.arrow"}]})
        body = MagicMock()
        body.iter_chunks.side_effect = self.iter_chunks
        self.s3.get_object = AsyncMock(
            return_value={"Body": body, "ContentLength": len(self.data), "ETag": '"test-etag"'}
        )

    async def iter_chunks(self, chunk_size: int) -> AsyncIterator[bytes]:
        task = asyncio.current_task()
        assert task is not None
        self.reader_tasks.append(task)
        yield self.data

    @contextlib.asynccontextmanager
    async def client(self) -> AsyncIterator[MagicMock]:
        self.producer_task = asyncio.current_task()
        try:
            yield self.s3
        finally:
            self.closing.set()
            await self.release_cleanup.wait()
            self.closed.set()


@pytest.fixture
def staged_export() -> Iterator[StagedExport]:
    staged = StagedExport()
    with patch("products.batch_exports.backend.temporal.pipeline.producer.get_s3_client", staged.client):
        yield staged


async def test_stop_waits_for_blocked_readers_and_s3_cleanup(staged_export: StagedExport) -> None:
    producer = Producer()
    queue = RecordBatchQueue(max_size_bytes=1)
    await producer.start(queue, "test-export", None, None, stage_folder="stage/")
    try:
        await queue.get_schema()
        assert queue.full()
        assert not producer.task.done()
        staged_export.release_cleanup.clear()

        stop_task = asyncio.create_task(producer.stop())
        await staged_export.closing.wait()
        assert not stop_task.done()
        assert all(task.done() for task in staged_export.reader_tasks)

        staged_export.release_cleanup.set()
        await stop_task
        assert producer.task.cancelled()
        assert staged_export.closed.is_set()
        await producer.stop()
    finally:
        staged_export.release_cleanup.set()
        producer.task.cancel()
        await asyncio.gather(producer.task, return_exceptions=True)


@pytest.mark.parametrize("failed", [False, True], ids=["completed", "failed"])
async def test_stop_preserves_finished_producer_result(staged_export: StagedExport, failed: bool) -> None:
    error = RuntimeError("Staging read failed")
    if failed:
        staged_export.s3.list_objects_v2.side_effect = error
    else:
        staged_export.s3.list_objects_v2.return_value = {}
    producer = Producer()
    await producer.start(RecordBatchQueue(), "test-export", None, None, stage_folder="stage/")
    await asyncio.wait([producer.task])

    await producer.stop()

    assert not producer.task.cancelled()
    assert producer.task.exception() is (error if failed else None)
    assert staged_export.closed.is_set()


@pytest.mark.parametrize("cancelled", [False, True], ids=["setup-failure", "activity-cancellation"])
async def test_bigquery_activity_stops_producer_before_exiting(staged_export: StagedExport, cancelled: bool) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    error = RuntimeError("Destination setup failed")

    async def get_or_create_table(table: object) -> None:
        entered.set()
        await release.wait()
        raise error

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get_or_create_table = get_or_create_table
    inputs = BigQueryInsertInputs(
        team_id=1,
        batch_export_id="test-export",
        data_interval_start="2026-01-01T00:00:00+00:00",
        data_interval_end="2026-01-01T01:00:00+00:00",
        stage_folder="stage/",
        dataset_id="test_dataset",
        table_id="test_table",
        integration_id=1,
    )
    integration = MagicMock(project_id="test-project")
    integration.has_key.return_value = True

    with (
        override_settings(BATCH_EXPORT_BIGQUERY_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES=1),
        patch(
            "products.batch_exports.backend.temporal.destinations.bigquery_batch_export."
            "_get_google_cloud_service_account_integration",
            AsyncMock(return_value=integration),
        ),
        patch.object(BigQueryClient, "from_service_account_integration", return_value=client),
    ):
        activity_task = asyncio.create_task(ActivityEnvironment().run(insert_into_bigquery_activity_from_stage, inputs))
        try:
            await entered.wait()
            assert staged_export.producer_task is not None
            assert not staged_export.producer_task.done()
            assert staged_export.reader_tasks
            if cancelled:
                activity_task.cancel()
            else:
                release.set()

            with pytest.raises(asyncio.CancelledError if cancelled else RuntimeError) as exc_info:
                await activity_task
            if not cancelled:
                assert exc_info.value is error
            assert staged_export.producer_task.cancelled()
            assert all(task.done() for task in staged_export.reader_tasks)
            assert staged_export.closed.is_set()
        finally:
            activity_task.cancel()
            await asyncio.gather(activity_task, return_exceptions=True)
            if staged_export.producer_task is not None:
                staged_export.producer_task.cancel()
                await asyncio.gather(staged_export.producer_task, return_exceptions=True)
