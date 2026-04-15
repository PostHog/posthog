"""Topic → producer routing.

Call sites specify a topic (or an explicit profile); the router resolves it to
a cluster profile and returns a producer configured for that profile. This
centralises cluster routing so moving a topic between clusters (e.g. MSK →
Warpstream) is a one-line change in TOPIC_ROUTING rather than a change at
every call site.

Two lifecycle shapes:

* Sync sites share a per-profile singleton (`get_producer`, `producer_scope`).
  Callers flush at end-of-work; they never close — the singleton outlives the
  caller.
* Async sites get a fresh producer per scope (`async_producer_scope`), because
  `_AsyncKafkaProducer.close()` permanently disables the underlying confluent
  AIOProducer — caching would leave later callers with a closed instance.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Optional

from django.conf import settings

from posthog.kafka_client.client import _AsyncKafkaProducer, _KafkaProducer
from posthog.kafka_client.topics import (
    KAFKA_DWH_CDP_RAW_TABLE,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS_DLQ,
    KAFKA_WAREHOUSE_SOURCES_JOBS,
    KAFKA_WAREHOUSE_SOURCES_JOBS_DLQ,
)


class KafkaClusterProfile(StrEnum):
    DEFAULT = "default"
    SESSION_RECORDING = "session_recording"
    WAREHOUSE_SOURCES = "warehouse_sources"
    CYCLOTRON = "cyclotron"


@dataclass(frozen=True)
class ClusterProfileConfig:
    hosts: list[str] | str
    security_protocol: Optional[str] = None
    acks: int | str = 1
    enable_idempotence: bool = False
    max_request_size: Optional[int] = None
    compression_type: Optional[str] = None


def _resolve_profile_config(profile: KafkaClusterProfile) -> ClusterProfileConfig:
    if profile == KafkaClusterProfile.DEFAULT:
        return ClusterProfileConfig(
            hosts=settings.KAFKA_HOSTS,
            security_protocol=settings.KAFKA_SECURITY_PROTOCOL,
        )
    if profile == KafkaClusterProfile.SESSION_RECORDING:
        return ClusterProfileConfig(
            hosts=settings.SESSION_RECORDING_KAFKA_HOSTS,
            security_protocol=settings.SESSION_RECORDING_KAFKA_SECURITY_PROTOCOL,
            max_request_size=settings.SESSION_RECORDING_KAFKA_MAX_REQUEST_SIZE_BYTES,
            compression_type="gzip",
        )
    if profile == KafkaClusterProfile.WAREHOUSE_SOURCES:
        return ClusterProfileConfig(
            hosts=settings.WAREHOUSE_PIPELINES_KAFKA_HOSTS,
            security_protocol=settings.WAREHOUSE_PIPELINES_KAFKA_SECURITY_PROTOCOL,
            acks="all",
            enable_idempotence=True,
        )
    if profile == KafkaClusterProfile.CYCLOTRON:
        return ClusterProfileConfig(
            hosts=settings.KAFKA_CYCLOTRON_WARPSTREAM_HOSTS,
            security_protocol=settings.KAFKA_CYCLOTRON_WARPSTREAM_PROTOCOL or "PLAINTEXT",
        )
    raise ValueError(f"Unknown KafkaClusterProfile: {profile}")


# Explicit topic → profile mapping. Topics not listed resolve to DEFAULT.
TOPIC_ROUTING: dict[str, KafkaClusterProfile] = {
    KAFKA_WAREHOUSE_SOURCES_JOBS: KafkaClusterProfile.WAREHOUSE_SOURCES,
    KAFKA_WAREHOUSE_SOURCES_JOBS_DLQ: KafkaClusterProfile.WAREHOUSE_SOURCES,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS: KafkaClusterProfile.WAREHOUSE_SOURCES,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS_DLQ: KafkaClusterProfile.WAREHOUSE_SOURCES,
    KAFKA_DWH_CDP_RAW_TABLE: KafkaClusterProfile.CYCLOTRON,
}


_SYNC_PRODUCERS: dict[KafkaClusterProfile, _KafkaProducer] = {}
_LOCK = Lock()


def _resolve_profile(topic: Optional[str], profile: Optional[KafkaClusterProfile]) -> KafkaClusterProfile:
    if profile is not None:
        return profile
    if topic is not None:
        return TOPIC_ROUTING.get(topic, KafkaClusterProfile.DEFAULT)
    return KafkaClusterProfile.DEFAULT


def _build_sync_producer(profile: KafkaClusterProfile) -> _KafkaProducer:
    config = _resolve_profile_config(profile)
    return _KafkaProducer(
        kafka_hosts=config.hosts,
        kafka_security_protocol=config.security_protocol,
        acks=config.acks,
        enable_idempotence=config.enable_idempotence,
        max_request_size=config.max_request_size,
        compression_type=config.compression_type,
    )


def _build_async_producer(profile: KafkaClusterProfile) -> _AsyncKafkaProducer:
    config = _resolve_profile_config(profile)
    return _AsyncKafkaProducer(
        kafka_hosts=config.hosts,
        kafka_security_protocol=config.security_protocol,
        max_request_size=config.max_request_size,
        compression_type=config.compression_type,
    )


def get_producer(
    *,
    topic: Optional[str] = None,
    profile: Optional[KafkaClusterProfile] = None,
) -> _KafkaProducer:
    """Return the singleton sync producer for the given topic or profile.

    Exactly one of `topic` or `profile` should typically be provided. If both
    are omitted, the DEFAULT profile is used. Callers should not close the
    returned producer — it is shared across the process.
    """
    resolved = _resolve_profile(topic, profile)
    with _LOCK:
        producer = _SYNC_PRODUCERS.get(resolved)
        if producer is None:
            producer = _build_sync_producer(resolved)
            _SYNC_PRODUCERS[resolved] = producer
        return producer


@contextmanager
def producer_scope(
    *,
    topic: Optional[str] = None,
    profile: Optional[KafkaClusterProfile] = None,
    flush_timeout: Optional[float] = None,
) -> Iterator[_KafkaProducer]:
    """Scope a block of sync produce calls against the singleton sync producer.

    Flushes on exit (success or error). Does not close — the singleton outlives
    this scope.
    """
    producer = get_producer(topic=topic, profile=profile)
    try:
        yield producer
    finally:
        producer.flush(flush_timeout)


@asynccontextmanager
async def async_producer_scope(
    *,
    topic: Optional[str] = None,
    profile: Optional[KafkaClusterProfile] = None,
) -> AsyncIterator[_AsyncKafkaProducer]:
    """Scope a fresh async producer for a block of work.

    Creates a new `_AsyncKafkaProducer` on entry. Flushes on successful exit
    and always closes on exit — the confluent AIOProducer cannot be reused
    once closed, so async producers are never cached.
    """
    resolved = _resolve_profile(topic, profile)
    producer = _build_async_producer(resolved)
    try:
        yield producer
        await producer.flush()
    finally:
        await producer.close()


def reset_producers() -> None:
    """Drop cached producers. For test hygiene."""
    with _LOCK:
        _SYNC_PRODUCERS.clear()
