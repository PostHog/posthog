import time
import asyncio

import pytest

from products.batch_exports.backend.temporal.pipeline.consumer import Consumer, ConsumerGroup, ConsumerGroupSettings
from products.batch_exports.backend.temporal.pipeline.transformer import (
    ChunkTransformerProtocol,
    JSONLStreamTransformer,
)
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue


class TestConsumer(Consumer):
    def __init__(self, model: str = "events"):
        super().__init__(model)
        self.chunks: list[bytes] = []

    async def consume_chunk(self, data: bytes):
        """Consume a chunk of data."""
        self.chunks.append(data)

    async def finalize_file(self):
        """Finalize the current file.

        Only called if working with multiple files, such as when we have a max file size.
        """
        pass

    async def finalize(self):
        """Finalize the consumer."""
        pass


class TestConsumerGroup(ConsumerGroup):
    def __init__(
        self,
        settings: ConsumerGroupSettings,
        queue: RecordBatchQueue,
        transformer: ChunkTransformerProtocol,
        producer_task: asyncio.Task,
        model: str = "events",
    ):
        self.settings = settings
        self.model = model
        self.queue = queue
        self.producer_task = producer_task
        self.transformer = transformer

    def build_consumer(self) -> TestConsumer:
        return TestConsumer(self.model)

    def run_consumer(self, consumer: TestConsumer):
        return consumer.run(self.queue, self.producer_task, self.transformer)


@pytest.mark.parametrize(
    "target_duration_seconds,total_size_bytes,bytes_exported,time_elapsed,current_number_of_consumers,max_consumers,min_consumers,expected,test_description",
    [
        (
            11,  # Target duration seconds
            2100,  # Total size bytes
            100,  # Bytes exported
            1,  # Time elapsed
            1,  # Current number of consumers
            3,  # Max consumers
            1,  # Min consumers
            1,  # Expected delta
            "2000 bytes left at 100B/s with 1 consumer should add 1 consumer to finish in 10 seconds left",
        ),
        (
            11,  # Target duration seconds
            1010,  # Total size bytes
            10,  # Bytes exported
            1,  # Time elapsed
            1,  # Current number of consumers
            4,  # Max consumers
            1,  # Min consumers
            3,  # Expected delta
            "1000 bytes left at 10B/s with 1 consumer needs 10 consumers but is capped to 4 so it only adds 3",
        ),
        (
            3,  # Target duration seconds
            2000,  # Total size bytes
            1000,  # Bytes exported
            1,  # Time elapsed
            2,  # Current number of consumers
            4,  # Max consumers
            1,  # Min consumers
            -1,  # Expected delta
            "1000 bytes left at 500B/s with 2 consumer should reduce 1 consumer to finish in 2 seconds left",
        ),
        (
            3,  # Target duration seconds
            2500,  # Total size bytes
            1500,  # Bytes exported
            1,  # Time elapsed
            3,  # Current number of consumers
            4,  # Max consumers
            2,  # Min consumers
            -1,  # Expected delta
            "1000 bytes left at 500B/s with 3 consumer needs only 1 consumer but is capped to 2 so it only takes 1",
        ),
    ],
)
async def test_calculate_consumers_delta(
    target_duration_seconds,
    total_size_bytes,
    bytes_exported,
    time_elapsed,
    current_number_of_consumers,
    max_consumers,
    min_consumers,
    expected,
    test_description,
):
    """Test _calculate_consumers_delta method with various scenarios.

    We manipulate the state of the group to assert the result of
     ``_calculate_consumers_delta``. The function normally uses a rolling window to
    update its state. For the purposes of this test, we set the window state equal to
    the overall state. This would be the same as the first window.
    """
    settings = ConsumerGroupSettings(
        target_duration_seconds=target_duration_seconds,
        total_size_bytes=total_size_bytes,
        max_consumers=max_consumers,
        min_consumers=min_consumers,
        # Rest of the settings don't matter for the purposes of this test
    )

    group = TestConsumerGroup(
        settings=settings,
        queue=RecordBatchQueue(),
        transformer=JSONLStreamTransformer(),
        producer_task=asyncio.create_task(asyncio.sleep(0)),
    )

    # Update state
    group.bytes_exported = group.bytes_exported_window = bytes_exported
    group.time_elapsed = group.time_elapsed_window = time_elapsed
    group._consumers = set(range(current_number_of_consumers))

    result = group._calculate_consumers_delta()

    assert result == expected, f"Failed: {test_description}"


def raise_if_task_failed(task):
    if task.done():
        exc = task.exception()

        if exc is not None:
            raise exc


async def test_consumer_group_adds_max_consumers_when_target_missed():
    """Test whether ``ConsumerGroup`` scales to maximum consumers when target duration is missed."""
    max_consumers = 10

    # Producer task will wait for 3 seconds before finishing
    producer_task = asyncio.create_task(asyncio.sleep(10))
    # Which is longer than our target of 0
    settings = ConsumerGroupSettings(
        target_duration_seconds=0,
        total_size_bytes=100 * 1024 * 1024,
        poll_delay_seconds=0.1,
        initial_grace_period_seconds=0,
        max_consumers=max_consumers,
    )

    group = TestConsumerGroup(
        settings=settings, queue=RecordBatchQueue(), transformer=JSONLStreamTransformer(), producer_task=producer_task
    )
    run_task = asyncio.create_task(group.run())

    try:
        # Let everything run until group detects its over
        async with asyncio.timeout(3):
            while not group.number_of_consumers == max_consumers:
                raise_if_task_failed(run_task)
                await asyncio.sleep(0)

        raise_if_task_failed(run_task)

        assert group.number_of_consumers == max_consumers
        assert group.is_over_target_duration(), f"Group running for {group.time_elapsed}, not yet over target duration"

    finally:
        # Clean-up
        producer_task.cancel()
        await asyncio.wait([producer_task, run_task])
        assert group.done()


async def test_consumer_group_poll():
    """Test ``ConsumerGroup`` polls all consumers for bytes exported and resets on window size."""
    producer_task = asyncio.create_task(asyncio.sleep(0))
    settings = ConsumerGroupSettings(
        target_duration_seconds=0,
        total_size_bytes=100 * 1024 * 1024,
        tracking_window_size=1,
    )

    group = TestConsumerGroup(
        settings=settings, queue=RecordBatchQueue(), transformer=JSONLStreamTransformer(), producer_task=producer_task
    )

    async with asyncio.TaskGroup() as tg:
        for _ in range(5):
            group._add_new_consumer(tg)

        for consumer in group.consumers:
            consumer.total_record_batch_bytes_count = 100

        # Manually start the group
        start = group._start_time = group._window_start_time = time.monotonic()

        group.poll()

        assert group.bytes_exported == 500
        assert group.bytes_exported_window == 500
        assert group.time_elapsed == group.last_poll_time - start
        assert group.time_elapsed_window == group.last_poll_time - start
        assert group.window_start_time == group.last_poll_time
        assert group._window_counter == 1

        previous_window_start_time = group.window_start_time

        for consumer in group.consumers:
            consumer.total_record_batch_bytes_count = 200

        group.poll()

        assert group.bytes_exported == 1000
        assert group.bytes_exported_window == 500
        assert group.time_elapsed == group.last_poll_time - start
        assert group.time_elapsed_window == group.last_poll_time - previous_window_start_time
        assert group.window_start_time == group.last_poll_time
        assert group._window_counter == 1


async def test_consumer_group_sets_task_name_for_consumers():
    """Test ``ConsumerGroup`` sets a task name for all consumers."""
    producer_task = asyncio.create_task(asyncio.sleep(0))
    settings = ConsumerGroupSettings(
        target_duration_seconds=0,
        total_size_bytes=0,
        tracking_window_size=1,
    )

    group = TestConsumerGroup(
        settings=settings, queue=RecordBatchQueue(), transformer=JSONLStreamTransformer(), producer_task=producer_task
    )

    async with asyncio.TaskGroup() as tg:
        for _ in range(3):
            group._add_new_consumer(tg)

        task_names = {consumer.task.get_name() for consumer in group.consumers}

        assert len(task_names) == 3
        assert "consumer-1" in task_names
        assert "consumer-2" in task_names
        assert "consumer-3" in task_names
