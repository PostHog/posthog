"""Kafka profile resolution and a bounded shadow-topic drain.

The drain reads each partition from `offsets_for_times(--since)` up to a high-watermark
snapshot taken at start, so a still-producing topic terminates. Uses a throwaway
consumer group with commits disabled and explicit `assign()` — a diagnostic tool must
never join or disturb a real consumer group.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from confluent_kafka import OFFSET_END, Consumer, KafkaError, TopicPartition

from posthog.kafka_client.profiles import KafkaClusterProfile
from posthog.kafka_client.routing import get_profile_settings

DEFAULT_SHADOW_TOPIC = "cohort_membership_changed_shadow"


@dataclass
class DrainStats:
    partitions: int = 0
    partitions_read: int = 0
    consumed: int = 0
    undecodable: int = 0
    # Earliest broker timestamp observed among partitions read from their low watermark.
    earliest_retained: Optional[datetime] = None
    # Partitions where retention already deleted offsets and the earliest retained
    # message is newer than --since: the fold cannot be proven complete.
    maybe_clipped_partitions: list[int] = field(default_factory=list)
    reached_end: bool = False


def consumer_config(
    *,
    hosts_override: Optional[str] = None,
    security_protocol_override: Optional[str] = None,
) -> dict[str, Any]:
    """Consumer config for the shadow topic's cluster (Warpstream ingestion).

    The shadow topic is not in the Django routing table, so the INGESTION profile is
    resolved explicitly; overrides serve local runs against a dev stack.
    """
    profile = get_profile_settings(profile=KafkaClusterProfile.INGESTION)
    hosts = hosts_override or ",".join(profile.hosts)
    config: dict[str, Any] = {
        "bootstrap.servers": hosts,
        "group.id": f"cohort-parity-{uuid.uuid4().hex[:8]}",
        "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
    }
    security_protocol = security_protocol_override or profile.security_protocol
    if security_protocol:
        config["security.protocol"] = security_protocol
    if security_protocol in ("SASL_PLAINTEXT", "SASL_SSL"):
        config["sasl.mechanism"] = profile.sasl_mechanism
        config["sasl.username"] = profile.sasl_user
        config["sasl.password"] = profile.sasl_password
    return config


def _broker_ts(message: Any) -> Optional[datetime]:
    _ts_type, ts_ms = message.timestamp()
    if ts_ms is None or ts_ms <= 0:
        return None
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC)


def drain_topic(
    topic: str,
    *,
    config: dict[str, Any],
    since: datetime,
    stats: DrainStats,
    max_messages: Optional[int] = None,
    poll_timeout: float = 5.0,
) -> Iterator[dict[str, Any]]:
    """Yield JSON-decoded messages from `since` up to the start-time high watermark."""
    consumer = Consumer(config)
    try:
        metadata = consumer.list_topics(topic, timeout=15)
        topic_meta = metadata.topics.get(topic)
        if topic_meta is None or topic_meta.error is not None:
            raise RuntimeError(f"topic {topic!r} not found: {topic_meta.error if topic_meta else 'no metadata'}")
        stats.partitions = len(topic_meta.partitions)

        since_ms = int(since.timestamp() * 1000)
        lows: dict[int, int] = {}
        highs: dict[int, int] = {}
        for partition in topic_meta.partitions:
            low, high = consumer.get_watermark_offsets(TopicPartition(topic, partition), timeout=15)
            lows[partition], highs[partition] = low, high

        start_requests = [TopicPartition(topic, p, since_ms) for p in sorted(lows) if highs[p] > lows[p]]
        starts = consumer.offsets_for_times(start_requests, timeout=15) if start_requests else []

        assignment: list[TopicPartition] = []
        remaining: dict[int, int] = {}  # partition → exclusive end offset (high-watermark snapshot)
        at_low: set[int] = set()  # partitions read from their low watermark (earliest retained data)
        for tp in starts:
            if tp.error is not None:
                raise RuntimeError(f"offsets_for_times failed for partition {tp.partition}: {tp.error}")
            if tp.offset < 0 or tp.offset == OFFSET_END or tp.offset >= highs[tp.partition]:
                continue  # no retained message at/after --since in this partition
            if tp.offset == lows[tp.partition]:
                at_low.add(tp.partition)
            remaining[tp.partition] = highs[tp.partition]
            assignment.append(TopicPartition(topic, tp.partition, tp.offset))

        stats.partitions_read = len(assignment)
        if not assignment:
            stats.reached_end = True
            return
        consumer.assign(assignment)

        first_seen: set[int] = set()
        while remaining:
            message = consumer.poll(timeout=poll_timeout)
            if message is None:
                return  # broker went quiet before the watermark snapshot — stats.reached_end stays False
            error = message.error()
            if error is not None:
                if error.code() == KafkaError._PARTITION_EOF:
                    continue
                raise RuntimeError(str(error))

            partition = message.partition()
            if partition in at_low and partition not in first_seen:
                first_seen.add(partition)
                ts = _broker_ts(message)
                if ts is not None:
                    if stats.earliest_retained is None or ts < stats.earliest_retained:
                        stats.earliest_retained = ts
                    if lows[partition] > 0 and ts > since:
                        stats.maybe_clipped_partitions.append(partition)

            value = message.value()
            if value is not None:
                try:
                    decoded = json.loads(value.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    stats.undecodable += 1
                else:
                    stats.consumed += 1
                    yield decoded
            if max_messages is not None and stats.consumed >= max_messages:
                return
            if partition in remaining and message.offset() + 1 >= remaining[partition]:
                del remaining[partition]
        stats.reached_end = True
    finally:
        consumer.close()
