"""Topic → producer routing.

Call sites specify a topic (or an explicit profile); the router resolves it to
a cluster profile and returns a lazily-created producer configured for that
profile. This centralises cluster routing so moving a topic between clusters
(e.g. MSK → Warpstream) is a one-line change in TOPIC_ROUTING rather than a
change at every call site.
"""

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
_ASYNC_PRODUCERS: dict[KafkaClusterProfile, _AsyncKafkaProducer] = {}
_LOCK = Lock()


def _resolve_profile(topic: Optional[str], profile: Optional[KafkaClusterProfile]) -> KafkaClusterProfile:
    if profile is not None:
        return profile
    if topic is not None:
        return TOPIC_ROUTING.get(topic, KafkaClusterProfile.DEFAULT)
    return KafkaClusterProfile.DEFAULT


def get_producer(
    *,
    topic: Optional[str] = None,
    profile: Optional[KafkaClusterProfile] = None,
) -> _KafkaProducer:
    """Return a sync producer for the given topic or profile.

    Exactly one of `topic` or `profile` should typically be provided. If both
    are omitted, the DEFAULT profile is used.
    """
    resolved = _resolve_profile(topic, profile)
    with _LOCK:
        producer = _SYNC_PRODUCERS.get(resolved)
        if producer is None:
            config = _resolve_profile_config(resolved)
            producer = _KafkaProducer(
                kafka_hosts=config.hosts,
                kafka_security_protocol=config.security_protocol,
                acks=config.acks,
                enable_idempotence=config.enable_idempotence,
                max_request_size=config.max_request_size,
                compression_type=config.compression_type,
            )
            _SYNC_PRODUCERS[resolved] = producer
        return producer


def get_async_producer(
    *,
    topic: Optional[str] = None,
    profile: Optional[KafkaClusterProfile] = None,
) -> _AsyncKafkaProducer:
    """Return an async producer for the given topic or profile."""
    resolved = _resolve_profile(topic, profile)
    with _LOCK:
        producer = _ASYNC_PRODUCERS.get(resolved)
        if producer is None:
            config = _resolve_profile_config(resolved)
            producer = _AsyncKafkaProducer(
                kafka_hosts=config.hosts,
                kafka_security_protocol=config.security_protocol,
                max_request_size=config.max_request_size,
                compression_type=config.compression_type,
            )
            _ASYNC_PRODUCERS[resolved] = producer
        return producer


def reset_producers() -> None:
    """Drop cached producers. For test hygiene."""
    with _LOCK:
        _SYNC_PRODUCERS.clear()
        _ASYNC_PRODUCERS.clear()
