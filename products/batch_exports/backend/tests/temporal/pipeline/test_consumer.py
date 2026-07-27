import asyncio

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
from structlog.testing import capture_logs

from products.batch_exports.backend.temporal.pipeline.consumer import Consumer, run_consumer_from_stage
from products.batch_exports.backend.temporal.pipeline.transformer import Chunk
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue

pytestmark = [pytest.mark.asyncio]


class NoOpConsumer(Consumer):
    async def consume_chunk(self, data: bytes):
        pass

    async def finalize_file(self):
        pass

    async def finalize(self):
        pass


class FakeTransformer:
    """Transformer yielding one fixed-size chunk per record batch."""

    def __init__(self, chunk_size: int = 10):
        self.chunk_size = chunk_size

    async def iter(self, record_batches):
        async for _ in record_batches:
            yield Chunk(b"x" * self.chunk_size, True)


def get_progress_logs(cap_logs) -> list[str]:
    """Returns the captured logs that are related to progress logging.

    `capture_logs` grabs the structured event dict before rendering, so the message is under
    "event". In production these go through LogMessagesRenderer and are emitted as JSON strings,
    so this dict-indexing only works under the test logging setup.
    """
    return [log["event"] for log in cap_logs if log["event"].startswith("Exported ~")]


@pytest.fixture
def consumer() -> NoOpConsumer:
    consumer = NoOpConsumer()
    consumer._start_monotonic = 0.0
    return consumer


@pytest.mark.parametrize(
    "records_done,records_total,expected_pct",
    [
        (0, 1000, None),
        (99, 1000, None),
        (100, 1000, 10),
        # Actual percentage is reported, not floored to the 10% step.
        (115, 1000, 11),
        (230, 1000, 23),
        (1000, 1000, 100),
        # Going over the estimate is clamped to 100%. Shouldn't happen in practice.
        (1500, 1000, 100),
    ],
)
async def test_maybe_log_progress_reports_actual_pct(consumer, records_done, records_total, expected_pct):
    consumer.records_total = records_total
    consumer.total_records_count = records_done

    with capture_logs() as cap_logs:
        consumer._maybe_log_progress()

    progress_logs = get_progress_logs(cap_logs)
    if expected_pct is None:
        assert progress_logs == []
    else:
        assert len(progress_logs) == 1
        assert progress_logs[0].startswith(f"Exported ~{expected_pct}%")


@pytest.mark.parametrize("records_total", [None, 0])
async def test_maybe_log_progress_is_silent_without_known_total(consumer, records_total):
    consumer.records_total = records_total
    consumer.total_records_count = 100

    with capture_logs() as cap_logs:
        consumer._maybe_log_progress()

    assert get_progress_logs(cap_logs) == []


async def test_maybe_log_progress_logs_each_step_once(consumer):
    consumer.records_total = 1000
    consumer.total_records_count = 110

    with capture_logs() as cap_logs:
        consumer._maybe_log_progress()
        consumer._maybe_log_progress()
        # Still within the same 10% step (19% < next threshold of 20%), so no new log.
        consumer.total_records_count = 190
        consumer._maybe_log_progress()
        consumer.total_records_count = 210
        consumer._maybe_log_progress()

    progress_logs = get_progress_logs(cap_logs)
    assert len(progress_logs) == 2
    assert progress_logs[0].startswith("Exported ~11%")
    assert progress_logs[1].startswith("Exported ~21%")


async def _put_record_batches_and_finish(queue: RecordBatchQueue, record_batches: list[pa.RecordBatch]) -> None:
    for record_batch in record_batches:
        await queue.put(record_batch)


@pytest.fixture
def mock_metrics():
    consumer_module = "products.batch_exports.backend.temporal.pipeline.consumer"
    with (
        patch(f"{consumer_module}.get_rows_exported_metric", return_value=MagicMock()),
        patch(f"{consumer_module}.get_bytes_exported_metric", return_value=MagicMock()),
    ):
        yield


async def test_run_consumer_from_stage_logs_progress_throughout(mock_metrics):
    consumer = NoOpConsumer()
    queue = RecordBatchQueue()
    # 10 batches of 10 records against a known total of 100, so each batch crosses a 10% step.
    record_batches = [pa.RecordBatch.from_pydict({"value": list(range(10))}) for _ in range(10)]
    producer_task = asyncio.create_task(_put_record_batches_and_finish(queue, record_batches))

    with capture_logs() as cap_logs:
        result = await run_consumer_from_stage(
            queue=queue,
            consumer=consumer,
            producer_task=producer_task,
            transformer=FakeTransformer(chunk_size=10),
            json_columns=(),
            records_total=100,
        )

    assert consumer.records_total == 100
    assert result.records_completed == 100
    progress_logs = get_progress_logs(cap_logs)
    assert [log.split("%")[0] for log in progress_logs] == [f"Exported ~{step}" for step in range(10, 101, 10)]
