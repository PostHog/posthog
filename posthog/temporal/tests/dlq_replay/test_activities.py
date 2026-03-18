import ssl
import uuid
import asyncio
import datetime as dt

import pytest

from django.conf import settings

import aiokafka
import pytest_asyncio
from aiokafka import TopicPartition
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from temporalio.testing import ActivityEnvironment

from posthog.temporal.dlq_replay.activities import (
    GetTopicPartitionsInputs,
    ReplayPartitionInputs,
    get_topic_partitions,
    replay_partition,
)

pytestmark = pytest.mark.asyncio


def configure_ssl_context() -> ssl.SSLContext | None:
    """Configure SSL context for Kafka if needed."""
    if settings.KAFKA_SECURITY_PROTOCOL != "SSL":
        return None

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.options |= ssl.OP_NO_SSLv2
    context.options |= ssl.OP_NO_SSLv3
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_default_certs()
    return context


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return ActivityEnvironment()


@pytest_asyncio.fixture
async def kafka_producer():
    """Create a Kafka producer for test setup."""
    ssl_context = configure_ssl_context()
    producer = aiokafka.AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_HOSTS,
        security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
        ssl_context=ssl_context,
        acks="all",
        api_version="2.5.0",
    )
    await producer.start()
    yield producer
    await producer.stop()


@pytest_asyncio.fixture
async def kafka_consumer():
    """Create a Kafka consumer for test verification."""
    ssl_context = configure_ssl_context()
    consumer = aiokafka.AIOKafkaConsumer(
        bootstrap_servers=settings.KAFKA_HOSTS,
        security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
        ssl_context=ssl_context,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        api_version="2.5.0",
    )
    await consumer.start()
    yield consumer
    await consumer.stop()


@pytest.fixture
def test_topics():
    """Generate unique topic names for each test."""
    unique_id = uuid.uuid4().hex[:8]
    return {
        "source": f"test_dlq_source_{unique_id}",
        "target": f"test_dlq_target_{unique_id}",
    }


async def test_get_topic_partitions_returns_partition_list(activity_environment, test_topics):
    """Test that get_topic_partitions returns the list of partitions for a topic."""
    ssl_context = configure_ssl_context()
    source_topic = test_topics["source"]

    # Create the topic explicitly using admin client
    admin_client = AIOKafkaAdminClient(
        bootstrap_servers=settings.KAFKA_HOSTS,
        security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
        ssl_context=ssl_context,
    )
    await admin_client.start()
    try:
        new_topic = NewTopic(name=source_topic, num_partitions=3, replication_factor=1)
        await admin_client.create_topics([new_topic])
    finally:
        await admin_client.close()

    result = await activity_environment.run(
        get_topic_partitions,
        GetTopicPartitionsInputs(topic=source_topic),
    )

    assert isinstance(result, list)
    assert len(result) == 3
    assert result == [0, 1, 2]


async def test_get_topic_partitions_returns_empty_for_nonexistent_topic(activity_environment):
    """Test that get_topic_partitions returns empty list for nonexistent topic."""
    result = await activity_environment.run(
        get_topic_partitions,
        GetTopicPartitionsInputs(topic="nonexistent_topic_that_does_not_exist_12345"),
    )

    assert result == []


async def test_replay_partition_replays_messages_within_time_range(
    activity_environment,
    kafka_producer,
    kafka_consumer,
    test_topics,
):
    """Test that replay_partition correctly replays messages within the time range."""
    source_topic = test_topics["source"]
    target_topic = test_topics["target"]

    # Produce test messages to the source topic
    base_time = dt.datetime.now(dt.UTC)
    messages_to_send = [
        {
            "key": f"key_{i}".encode(),
            "value": f"message_{i}".encode(),
            "headers": [("header_key", f"header_value_{i}".encode())],
        }
        for i in range(5)
    ]

    for msg in messages_to_send:
        await kafka_producer.send(
            source_topic,
            value=msg["value"],
            key=msg["key"],
            headers=msg["headers"],
            partition=0,
        )
    await kafka_producer.flush()

    # Wait a bit for messages to be committed
    await asyncio.sleep(1)

    # Get the time range that covers all messages
    start_timestamp_ms = int((base_time - dt.timedelta(minutes=1)).timestamp() * 1000)
    end_timestamp_ms = int((base_time + dt.timedelta(minutes=1)).timestamp() * 1000)

    # Run the replay activity
    result = await activity_environment.run(
        replay_partition,
        ReplayPartitionInputs(
            source_topic=source_topic,
            target_topic=target_topic,
            partition=0,
            start_timestamp_ms=start_timestamp_ms,
            end_timestamp_ms=end_timestamp_ms,
            batch_size=100,
        ),
    )

    assert result.partition == 0
    assert result.messages_replayed == 5

    # Verify messages were replayed to target topic
    tp = TopicPartition(target_topic, 0)
    kafka_consumer.assign([tp])
    await kafka_consumer.seek_to_beginning(tp)

    replayed_messages = []
    records = await kafka_consumer.getmany(tp, timeout_ms=5000, max_records=10)
    if tp in records:
        replayed_messages = records[tp]

    assert len(replayed_messages) == 5

    for i, record in enumerate(replayed_messages):
        assert record.key == f"key_{i}".encode()
        assert record.value == f"message_{i}".encode()
        # Headers are returned as tuple of tuples from consumer
        assert record.headers == (("header_key", f"header_value_{i}".encode()),)


async def test_replay_partition_respects_end_timestamp(
    activity_environment,
    kafka_producer,
    kafka_consumer,
    test_topics,
):
    """Test that replay_partition stops at end_timestamp."""
    source_topic = test_topics["source"]
    target_topic = test_topics["target"]

    # Get the start time before sending any messages
    start_time = dt.datetime.now(dt.UTC)

    # Send first batch with explicit timestamps in the past
    early_timestamp_ms = int((start_time - dt.timedelta(seconds=30)).timestamp() * 1000)
    for i in range(3):
        await kafka_producer.send(
            source_topic,
            value=f"early_message_{i}".encode(),
            partition=0,
            timestamp_ms=early_timestamp_ms + i,  # Slightly different timestamps
        )
    await kafka_producer.flush()

    # Mid time - between the two batches
    mid_timestamp_ms = int(start_time.timestamp() * 1000)

    # Send second batch with timestamps after mid_time
    late_timestamp_ms = int((start_time + dt.timedelta(seconds=30)).timestamp() * 1000)
    for i in range(3):
        await kafka_producer.send(
            source_topic,
            value=f"late_message_{i}".encode(),
            partition=0,
            timestamp_ms=late_timestamp_ms + i,
        )
    await kafka_producer.flush()

    # Replay only messages before mid_time
    start_timestamp_ms = int((start_time - dt.timedelta(minutes=1)).timestamp() * 1000)

    result = await activity_environment.run(
        replay_partition,
        ReplayPartitionInputs(
            source_topic=source_topic,
            target_topic=target_topic,
            partition=0,
            start_timestamp_ms=start_timestamp_ms,
            end_timestamp_ms=mid_timestamp_ms,
            batch_size=100,
        ),
    )

    # Should only replay the first batch (early messages)
    assert result.messages_replayed == 3

    # Verify only early messages were replayed
    tp = TopicPartition(target_topic, 0)
    kafka_consumer.assign([tp])
    await kafka_consumer.seek_to_beginning(tp)

    records = await kafka_consumer.getmany(tp, timeout_ms=5000, max_records=10)
    replayed_messages = records.get(tp, [])

    assert len(replayed_messages) == 3
    for record in replayed_messages:
        assert record.value.decode().startswith("early_message_")


async def test_replay_partition_handles_empty_partition(
    activity_environment,
    test_topics,
):
    """Test that replay_partition handles partitions with no messages in time range."""
    source_topic = test_topics["source"]
    target_topic = test_topics["target"]

    # Use a time range in the past where no messages exist
    past_time = dt.datetime.now(dt.UTC) - dt.timedelta(days=365)
    start_timestamp_ms = int(past_time.timestamp() * 1000)
    end_timestamp_ms = int((past_time + dt.timedelta(hours=1)).timestamp() * 1000)

    result = await activity_environment.run(
        replay_partition,
        ReplayPartitionInputs(
            source_topic=source_topic,
            target_topic=target_topic,
            partition=0,
            start_timestamp_ms=start_timestamp_ms,
            end_timestamp_ms=end_timestamp_ms,
            batch_size=100,
        ),
    )

    assert result.partition == 0
    assert result.messages_replayed == 0
