import ssl
import asyncio
import dataclasses

from django.conf import settings

import aiokafka
from aiokafka import TopicPartition
from structlog import get_logger
from temporalio import activity

from posthog.temporal.common.heartbeat import Heartbeater

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class GetTopicPartitionsInputs:
    """Inputs for the get_topic_partitions activity."""

    topic: str


@dataclasses.dataclass
class ReplayPartitionInputs:
    """Inputs for the replay_partition activity.

    Attributes:
        source_topic: The DLQ topic to read messages from.
        target_topic: The topic to replay messages to.
        partition: The partition to replay.
        start_timestamp_ms: The timestamp (in milliseconds) to start reading from.
        end_timestamp_ms: The timestamp (in milliseconds) to stop reading at.
        batch_size: Number of messages to process in each batch before flushing.
        token_allowlist: Optional list of token values. When set, only messages whose
            `token` Kafka header matches one of these values are replayed; all others
            are skipped (including messages without a `token` header).
    """

    source_topic: str
    target_topic: str
    partition: int
    start_timestamp_ms: int
    end_timestamp_ms: int
    batch_size: int = 1000
    token_allowlist: list[str] | None = None


@dataclasses.dataclass
class ReplayPartitionResult:
    """Result of the replay_partition activity.

    Attributes:
        partition: The partition that was replayed.
        messages_replayed: Number of messages replayed from this partition.
        messages_skipped: Number of messages read but skipped by the token allowlist.
    """

    partition: int
    messages_replayed: int
    messages_skipped: int = 0


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


@activity.defn
async def get_topic_partitions(inputs: GetTopicPartitionsInputs) -> list[int]:
    """Get all partition numbers for a Kafka topic."""
    logger = LOGGER.bind(topic=inputs.topic)
    logger.info("Getting partitions for topic")

    ssl_context = configure_ssl_context()

    consumer = aiokafka.AIOKafkaConsumer(
        bootstrap_servers=settings.KAFKA_HOSTS,
        security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
        ssl_context=ssl_context,
        api_version="2.5.0",
    )

    await consumer.start()
    try:
        # Force a metadata refresh for the specific topic
        await consumer._client.force_metadata_update()

        # partitions_for_topic is not async - it returns a set or None
        partitions_info = consumer.partitions_for_topic(inputs.topic)
        if partitions_info is None:
            logger.warning("Topic not found or has no partitions")
            return []

        partitions = sorted(partitions_info)
        logger.info("Found partitions", partitions=partitions, partition_count=len(partitions))
        return partitions
    finally:
        try:
            await consumer.stop()
        except asyncio.CancelledError:
            # aiokafka can raise CancelledError during stop if internal tasks are cancelled
            pass


@activity.defn
async def replay_partition(inputs: ReplayPartitionInputs) -> ReplayPartitionResult:
    """Replay messages from a single partition of a DLQ topic to a target topic.

    This activity reads messages from a specific partition of the source (DLQ) topic
    starting from a given timestamp and produces them to the target topic.
    """
    logger = LOGGER.bind(
        source_topic=inputs.source_topic,
        target_topic=inputs.target_topic,
        partition=inputs.partition,
        start_timestamp_ms=inputs.start_timestamp_ms,
        end_timestamp_ms=inputs.end_timestamp_ms,
    )
    logger.info("Starting partition replay")

    ssl_context = configure_ssl_context()

    consumer = aiokafka.AIOKafkaConsumer(
        bootstrap_servers=settings.KAFKA_HOSTS,
        security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
        ssl_context=ssl_context,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        api_version="2.5.0",
    )

    producer = aiokafka.AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_HOSTS,
        security_protocol=settings.KAFKA_SECURITY_PROTOCOL or "PLAINTEXT",
        ssl_context=ssl_context,
        acks="all",
        api_version="2.5.0",
    )

    messages_replayed = 0
    messages_skipped = 0
    token_allowlist_bytes: set[bytes] | None = (
        {token.encode() for token in inputs.token_allowlist} if inputs.token_allowlist is not None else None
    )

    async with Heartbeater():
        await consumer.start()
        await producer.start()

        try:
            tp = TopicPartition(inputs.source_topic, inputs.partition)
            consumer.assign([tp])

            # Get the offset for the start timestamp
            offsets = await consumer.offsets_for_times({tp: inputs.start_timestamp_ms})
            start_offset_and_timestamp = offsets.get(tp)

            if start_offset_and_timestamp is None:
                logger.info("No messages found at or after start timestamp")
                return ReplayPartitionResult(partition=inputs.partition, messages_replayed=0)

            consumer.seek(tp, start_offset_and_timestamp.offset)
            logger.info("Consumer seeked to offset", start_offset=start_offset_and_timestamp.offset)

            while True:
                # Fetch a batch of messages
                records = await consumer.getmany(tp, timeout_ms=5000, max_records=inputs.batch_size)

                if not records or tp not in records or len(records[tp]) == 0:
                    logger.info(
                        "No more messages available",
                        messages_replayed=messages_replayed,
                        messages_skipped=messages_skipped,
                    )
                    break

                batch = records[tp]
                batch_futures = []
                reached_end = False

                for record in batch:
                    # Check if we've passed the end timestamp
                    if record.timestamp > inputs.end_timestamp_ms:
                        logger.info(
                            "Reached end timestamp",
                            current_timestamp=record.timestamp,
                            end_timestamp_ms=inputs.end_timestamp_ms,
                        )
                        reached_end = True
                        break

                    headers = list(record.headers) if record.headers else []

                    if token_allowlist_bytes is not None:
                        token = next((v for k, v in headers if k == "token"), None)
                        if token not in token_allowlist_bytes:
                            messages_skipped += 1
                            continue

                    # Produce the message to the target topic, preserving key, value, and headers.
                    # aiokafka producer expects a list of header tuples, not the tuple-of-tuples the consumer returns.
                    future = await producer.send(
                        inputs.target_topic,
                        value=record.value,
                        key=record.key,
                        headers=headers,
                    )
                    batch_futures.append(future)
                    messages_replayed += 1

                # Wait for all messages in the batch to be sent
                for future in batch_futures:
                    await future

                await producer.flush()

                logger.info(
                    "Batch processed",
                    batch_size=len(batch),
                    messages_replayed=messages_replayed,
                    messages_skipped=messages_skipped,
                )

                # Heartbeat for progress tracking
                activity.heartbeat({"messages_replayed": messages_replayed, "messages_skipped": messages_skipped})

                if reached_end:
                    break

        finally:
            await consumer.stop()
            await producer.stop()

    logger.info(
        "Partition replay completed",
        messages_replayed=messages_replayed,
        messages_skipped=messages_skipped,
    )

    return ReplayPartitionResult(
        partition=inputs.partition,
        messages_replayed=messages_replayed,
        messages_skipped=messages_skipped,
    )
