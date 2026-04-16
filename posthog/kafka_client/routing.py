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
from threading import Lock
from typing import Optional

from django.conf import settings

from posthog.kafka_client.client import _AsyncKafkaProducer, _KafkaProducer
from posthog.kafka_client.profiles import KafkaClusterProfile
from posthog.kafka_client.topics import (
    KAFKA_DWH_CDP_RAW_TABLE,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS_DLQ,
    KAFKA_WAREHOUSE_SOURCES_JOBS,
    KAFKA_WAREHOUSE_SOURCES_JOBS_DLQ,
)


@dataclass(frozen=True)
class ClusterProfileConfig:
    hosts: list[str] | str
    security_protocol: Optional[str] = None
    acks: int | str = 1
    enable_idempotence: bool = False
    max_request_size: Optional[int] = None
    compression_type: Optional[str] = None


def _resolve_profile_config(profile: KafkaClusterProfile) -> ClusterProfileConfig:
    """Read the fully resolved profile settings from `settings.KAFKA_PROFILES`.

    Profile-level defaults (acks, enable_idempotence, compression_type,
    max_request_size) come from the profile's `producer_settings` which is
    itself the code defaults layered with `KAFKA_<PROFILE>_*` env vars and
    legacy aliases. See `posthog/settings/kafka.py`.
    """
    profile_settings = settings.KAFKA_PROFILES[profile.value]
    producer = profile_settings.producer_settings
    return ClusterProfileConfig(
        hosts=profile_settings.hosts,
        security_protocol=profile_settings.security_protocol
        or ("PLAINTEXT" if profile == KafkaClusterProfile.CYCLOTRON else None),
        acks=producer.get("acks", 1),
        enable_idempotence=producer.get("enable_idempotence", False),
        max_request_size=producer.get("max_request_size"),
        compression_type=producer.get("compression_type"),
    )


# Code-level default topic → profile mapping. Topics not listed resolve to DEFAULT.
# Callers should not read this directly — use `current_topic_routing()` so env
# overrides from `KAFKA_TOPIC_ROUTING_OVERRIDES` are applied.
_DEFAULT_TOPIC_ROUTING: dict[str, KafkaClusterProfile] = {
    KAFKA_WAREHOUSE_SOURCES_JOBS: KafkaClusterProfile.WAREHOUSE_SOURCES,
    KAFKA_WAREHOUSE_SOURCES_JOBS_DLQ: KafkaClusterProfile.WAREHOUSE_SOURCES,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS: KafkaClusterProfile.WAREHOUSE_SOURCES,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS_DLQ: KafkaClusterProfile.WAREHOUSE_SOURCES,
    KAFKA_DWH_CDP_RAW_TABLE: KafkaClusterProfile.CYCLOTRON,
}


def _parse_routing_overrides(raw: str) -> dict[str, KafkaClusterProfile]:
    """Parse 'topic_a=profile_a,topic_b=profile_b' into a dict.

    Raises ValueError on malformed entries or unknown profile names so
    misconfiguration surfaces at startup rather than silently defaulting.
    """
    overrides: dict[str, KafkaClusterProfile] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        topic, sep, profile_name = chunk.partition("=")
        topic, profile_name = topic.strip(), profile_name.strip()
        if not sep or not topic or not profile_name:
            raise ValueError(f"Malformed KAFKA_TOPIC_ROUTING_OVERRIDES entry: {chunk!r} (expected 'topic=profile')")
        try:
            overrides[topic] = KafkaClusterProfile(profile_name)
        except ValueError:
            valid = ", ".join(p.value for p in KafkaClusterProfile)
            raise ValueError(
                f"Unknown profile {profile_name!r} for topic {topic!r} in KAFKA_TOPIC_ROUTING_OVERRIDES "
                f"(valid profiles: {valid})"
            ) from None
    return overrides


def current_topic_routing() -> dict[str, KafkaClusterProfile]:
    """Return the merged routing map: code defaults overlaid with env overrides.

    Re-reads `settings.KAFKA_TOPIC_ROUTING_OVERRIDES` on every call so tests that
    use `override_settings` can change routing without reimporting the module.
    """
    raw = getattr(settings, "KAFKA_TOPIC_ROUTING_OVERRIDES", "") or ""
    if not raw.strip():
        return _DEFAULT_TOPIC_ROUTING
    return {**_DEFAULT_TOPIC_ROUTING, **_parse_routing_overrides(raw)}


_SYNC_PRODUCERS: dict[KafkaClusterProfile, _KafkaProducer] = {}
_LOCK = Lock()


def _resolve_profile(topic: Optional[str], profile: Optional[KafkaClusterProfile]) -> KafkaClusterProfile:
    if profile is not None:
        return profile
    if topic is not None:
        return current_topic_routing().get(topic, KafkaClusterProfile.DEFAULT)
    return KafkaClusterProfile.DEFAULT


def _build_sync_producer(profile: KafkaClusterProfile) -> _KafkaProducer:
    config = _resolve_profile_config(profile)
    profile_settings = settings.KAFKA_PROFILES[profile.value]
    return _KafkaProducer(
        kafka_hosts=config.hosts,
        kafka_security_protocol=config.security_protocol,
        sasl_mechanism=profile_settings.sasl_mechanism,
        sasl_user=profile_settings.sasl_user,
        sasl_password=profile_settings.sasl_password,
        acks=config.acks,
        enable_idempotence=config.enable_idempotence,
        max_request_size=config.max_request_size,
        compression_type=config.compression_type,
        producer_settings=profile_settings.producer_settings,
    )


def _build_async_producer(profile: KafkaClusterProfile) -> _AsyncKafkaProducer:
    config = _resolve_profile_config(profile)
    profile_settings = settings.KAFKA_PROFILES[profile.value]
    return _AsyncKafkaProducer(
        kafka_hosts=config.hosts,
        kafka_security_protocol=config.security_protocol,
        sasl_mechanism=profile_settings.sasl_mechanism,
        sasl_user=profile_settings.sasl_user,
        sasl_password=profile_settings.sasl_password,
        max_request_size=config.max_request_size,
        compression_type=config.compression_type,
        producer_settings=profile_settings.producer_settings,
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


def new_async_producer(
    *,
    profile: Optional[KafkaClusterProfile] = None,
    topic: Optional[str] = None,
) -> _AsyncKafkaProducer:
    """Construct a fresh async producer the caller fully owns.

    For long-lived consumers (e.g. the Temporal logger daemon) where the
    producer outlives any single scope. The caller is responsible for closing
    it. For per-call work prefer `async_producer_scope`.
    """
    resolved = _resolve_profile(topic, profile)
    return _build_async_producer(resolved)


def producer_for_config(
    *,
    hosts: list[str] | str,
    security_protocol: Optional[str] = None,
    acks: int | str = 1,
    enable_idempotence: bool = False,
    max_request_size: Optional[int] = None,
    compression_type: Optional[str] = None,
) -> _KafkaProducer:
    """Construct a sync producer with explicit cluster config (no profile lookup).

    For DLQ consumers that need to mirror the cluster they are reading from,
    or other rare cases where hosts are only known at runtime. The returned
    producer is not cached — the caller owns it and is responsible for flush.
    """
    return _KafkaProducer(
        kafka_hosts=hosts,
        kafka_security_protocol=security_protocol,
        acks=acks,
        enable_idempotence=enable_idempotence,
        max_request_size=max_request_size,
        compression_type=compression_type,
    )


def flush_all_producers(timeout: Optional[float] = None) -> None:
    """Flush every cached sync producer.

    Useful from management commands and other terminating contexts where the
    process is about to exit and may have produced to several topics across
    multiple profiles.
    """
    with _LOCK:
        producers = list(_SYNC_PRODUCERS.values())
    for producer in producers:
        producer.flush(timeout)


def reset_producers() -> None:
    """Drop cached producers. For test hygiene."""
    with _LOCK:
        _SYNC_PRODUCERS.clear()
