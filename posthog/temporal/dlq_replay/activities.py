import ssl
import asyncio
import dataclasses
from typing import Any

from django.conf import settings

import aiokafka
from aiokafka import TopicPartition
from structlog import get_logger
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.kafka_client.routing import get_profile_settings
from posthog.settings.kafka import KafkaProfileSettings
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
    """

    source_topic: str
    target_topic: str
    partition: int
    start_timestamp_ms: int
    end_timestamp_ms: int
    batch_size: int = 1000


@dataclasses.dataclass
class ReplayPartitionResult:
    """Result of the replay_partition activity.

    Attributes:
        partition: The partition that was replayed.
        messages_replayed: Number of messages replayed from this partition.
    """

    partition: int
    messages_replayed: int


_ENCRYPTED_PROTOCOLS = frozenset({"SSL", "SASL_SSL"})
_SASL_PROTOCOLS = frozenset({"SASL_PLAINTEXT", "SASL_SSL"})


def configure_ssl_context(security_protocol: str | None) -> ssl.SSLContext | None:
    """Configure SSL context for Kafka if the profile encrypts the connection."""
    if security_protocol not in _ENCRYPTED_PROTOCOLS:
        return None

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.options |= ssl.OP_NO_SSLv2
    context.options |= ssl.OP_NO_SSLv3
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_default_certs()
    return context


def resolve_topic_profile(topic: str) -> KafkaProfileSettings:
    """Resolve the cluster profile for a topic, and reject an unusable one.

    Outside dev, a profile with no hosts env var keeps the dev-local fallback host,
    which no deployment can reach. Report that as a config error, because a
    connection timeout sends the reader after the cluster instead of the config.
    """
    profile = get_profile_settings(topic=topic)

    if not profile.hosts_configured and not (settings.DEBUG or settings.TEST):
        raise ApplicationError(
            f"Kafka profile '{profile.name}' for topic '{topic}' has no hosts. "
            f"Set KAFKA_{profile.name.upper()}_HOSTS or KAFKA_DEFAULT_HOSTS.",
            non_retryable=True,
        )

    if profile.security_protocol in _SASL_PROTOCOLS and not (profile.sasl_mechanism and profile.sasl_user):
        raise ApplicationError(
            f"Kafka profile '{profile.name}' uses {profile.security_protocol} but has no SASL credentials. "
            f"Set KAFKA_{profile.name.upper()}_SASL_MECHANISM, _SASL_USER, and _SASL_PASSWORD.",
            non_retryable=True,
        )

    return profile


def client_kwargs(profile: KafkaProfileSettings) -> dict[str, Any]:
    """Connection arguments shared by every aiokafka client in this module.

    aiokafka takes the SASL credentials at construction time only. A client built
    without them cannot authenticate against a SASL cluster.
    """
    security_protocol = profile.security_protocol or "PLAINTEXT"
    kwargs: dict[str, Any] = {
        "bootstrap_servers": profile.hosts,
        "security_protocol": security_protocol,
        "ssl_context": configure_ssl_context(security_protocol),
        "api_version": "2.5.0",
    }
    if security_protocol in _SASL_PROTOCOLS:
        kwargs["sasl_mechanism"] = profile.sasl_mechanism
        kwargs["sasl_plain_username"] = profile.sasl_user
        kwargs["sasl_plain_password"] = profile.sasl_password
    return kwargs


@activity.defn
async def get_topic_partitions(inputs: GetTopicPartitionsInputs) -> list[int]:
    """Get all partition numbers for a Kafka topic."""
    logger = LOGGER.bind(topic=inputs.topic)
    logger.info("Getting partitions for topic")

    profile = resolve_topic_profile(inputs.topic)

    consumer = aiokafka.AIOKafkaConsumer(**client_kwargs(profile))

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

    source_profile = resolve_topic_profile(inputs.source_topic)

    consumer = aiokafka.AIOKafkaConsumer(
        **client_kwargs(source_profile),
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )

    # Replay must preserve per-message headers, which confluent-kafka's AIOProducer
    # refuses to pass through in batch mode. Use aiokafka directly for this activity
    # only — cluster routing still flows through `get_profile_settings(topic=...)`.
    target_profile = resolve_topic_profile(inputs.target_topic)
    producer = aiokafka.AIOKafkaProducer(
        **client_kwargs(target_profile),
        acks="all",
    )

    messages_replayed = 0

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
                    logger.info("No more messages available", messages_replayed=messages_replayed)
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

                    # Produce the message to the target topic, preserving key, value, and headers.
                    # aiokafka expects `list[tuple[str, bytes]]`, which is what record.headers
                    # already is.
                    headers = list(record.headers) if record.headers else []
                    future = await producer.send(
                        topic=inputs.target_topic,
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
                )

                # Heartbeat for progress tracking
                activity.heartbeat({"messages_replayed": messages_replayed})

                if reached_end:
                    break

        finally:
            try:
                await consumer.stop()
            except asyncio.CancelledError:
                pass
            try:
                await producer.stop()
            except asyncio.CancelledError:
                pass

    logger.info("Partition replay completed", messages_replayed=messages_replayed)

    return ReplayPartitionResult(partition=inputs.partition, messages_replayed=messages_replayed)
