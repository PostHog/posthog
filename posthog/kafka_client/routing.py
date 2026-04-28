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
from threading import Lock
from typing import Optional

from django.conf import settings

from posthog.kafka_client.client import _AsyncKafkaProducer, _KafkaProducer
from posthog.kafka_client.profiles import KafkaClusterProfile
from posthog.kafka_client.topics import (
    KAFKA_APP_METRICS2,
    KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
    KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS,
    KAFKA_CDP_INTERNAL_EVENTS,
    KAFKA_COHORT_MEMBERSHIP_CHANGED,
    KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC,
    KAFKA_DOCUMENT_EMBEDDINGS_TOPIC,
    KAFKA_DWH_CDP_RAW_TABLE,
    KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_EMBEDDINGS,
    KAFKA_EVENTS_JSON,
    KAFKA_GROUPS,
    KAFKA_LOG_ENTRIES,
    KAFKA_METRICS_TIME_TO_SEE_DATA,
    KAFKA_NOTIFICATION_EVENTS,
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_SIGNALS_REPORT_COMPLETED,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS_DLQ,
    KAFKA_WAREHOUSE_SOURCES_JOBS,
    KAFKA_WAREHOUSE_SOURCES_JOBS_DLQ,
)
from posthog.settings.kafka import KafkaProfileSettings

# Code-level default topic → profile mapping.
#
# Every topic Django produces to is listed explicitly so the full routing surface
# is visible in one place. Topics not listed still fall through to DEFAULT.
#
# To move a topic to a different cluster at deploy time without a code change,
# set `KAFKA_TOPIC_ROUTING_OVERRIDES=topic_name=profile_name` in the chart env.
_DEFAULT_TOPIC_ROUTING: dict[str, KafkaClusterProfile] = {
    # --- DEFAULT (MSK events cluster) ---
    KAFKA_EVENTS_JSON: KafkaClusterProfile.DEFAULT,
    KAFKA_PERSON: KafkaClusterProfile.DEFAULT,
    KAFKA_PERSON_DISTINCT_ID: KafkaClusterProfile.DEFAULT,
    KAFKA_GROUPS: KafkaClusterProfile.DEFAULT,
    KAFKA_METRICS_TIME_TO_SEE_DATA: KafkaClusterProfile.DEFAULT,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT: KafkaClusterProfile.DEFAULT,
    KAFKA_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE: KafkaClusterProfile.DEFAULT,
    KAFKA_ERROR_TRACKING_ISSUE_FINGERPRINT_EMBEDDINGS: KafkaClusterProfile.DEFAULT,
    KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC: KafkaClusterProfile.DEFAULT,
    KAFKA_DOCUMENT_EMBEDDINGS_TOPIC: KafkaClusterProfile.DEFAULT,
    KAFKA_NOTIFICATION_EVENTS: KafkaClusterProfile.DEFAULT,
    KAFKA_SIGNALS_REPORT_COMPLETED: KafkaClusterProfile.DEFAULT,
    # --- WAREHOUSE_SOURCES (Warpstream warehouse-pipelines) ---
    KAFKA_WAREHOUSE_SOURCES_JOBS: KafkaClusterProfile.WAREHOUSE_SOURCES,
    KAFKA_WAREHOUSE_SOURCES_JOBS_DLQ: KafkaClusterProfile.WAREHOUSE_SOURCES,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS: KafkaClusterProfile.WAREHOUSE_SOURCES,
    KAFKA_WAREHOUSE_SOURCE_WEBHOOKS_DLQ: KafkaClusterProfile.WAREHOUSE_SOURCES,
    # --- CYCLOTRON (Warpstream cyclotron) ---
    KAFKA_CDP_INTERNAL_EVENTS: KafkaClusterProfile.DEFAULT,  # TODO: move to KafkaClusterProfile.CYCLOTRON
    KAFKA_DWH_CDP_RAW_TABLE: KafkaClusterProfile.CYCLOTRON,
    # --- AUX metrics ---
    KAFKA_LOG_ENTRIES: KafkaClusterProfile.DEFAULT,  # TODO: move to KafkaClusterProfile.INGESTION
    KAFKA_APP_METRICS2: KafkaClusterProfile.DEFAULT,  # TODO: move to KafkaClusterProfile.INGESTION
    # --- CALCULATED_EVENTS (Warpstream calculated-events) ---
    KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES: KafkaClusterProfile.DEFAULT,  # TODO: move to KafkaClusterProfile.CALCULATED_EVENTS
    KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS: KafkaClusterProfile.DEFAULT,  # TODO: move to KafkaClusterProfile.CALCULATED_EVENTS
    KAFKA_COHORT_MEMBERSHIP_CHANGED: KafkaClusterProfile.DEFAULT,  # TODO: move to KafkaClusterProfile.CALCULATED_EVENTS
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


def resolve_profile_name(
    *,
    topic: Optional[str] = None,
    profile: Optional[KafkaClusterProfile] = None,
) -> KafkaClusterProfile:
    """Return the cluster profile for a topic or explicit profile, honouring overrides."""
    if profile is not None:
        return profile
    if topic is not None:
        return current_topic_routing().get(topic, KafkaClusterProfile.DEFAULT)
    return KafkaClusterProfile.DEFAULT


def get_profile_settings(
    *,
    topic: Optional[str] = None,
    profile: Optional[KafkaClusterProfile] = None,
) -> KafkaProfileSettings:
    """Return the fully-resolved `KafkaProfileSettings` for a topic or profile.

    Use this from Kafka consumer classes that keep their own consumer
    construction but want hosts/security/SASL resolved through the router (so
    topics moved via `KAFKA_TOPIC_ROUTING_OVERRIDES` land on the right cluster).
    """
    resolved = resolve_profile_name(topic=topic, profile=profile)
    return settings.KAFKA_PROFILES[resolved.value]


def _build_sync_producer(profile: KafkaClusterProfile) -> _KafkaProducer:
    p = settings.KAFKA_PROFILES[profile.value]
    producer_settings = p.producer_settings
    return _KafkaProducer(
        kafka_hosts=p.hosts,
        kafka_security_protocol=p.security_protocol,
        sasl_mechanism=p.sasl_mechanism,
        sasl_user=p.sasl_user,
        sasl_password=p.sasl_password,
        acks=producer_settings.get("acks", 1),
        enable_idempotence=producer_settings.get("enable_idempotence", False),
        max_request_size=producer_settings.get("max_request_size"),
        compression_type=producer_settings.get("compression_type"),
        producer_settings=producer_settings,
    )


def _build_async_producer(
    profile: KafkaClusterProfile,
) -> _AsyncKafkaProducer:
    p = settings.KAFKA_PROFILES[profile.value]
    producer_settings = p.producer_settings
    return _AsyncKafkaProducer(
        kafka_hosts=p.hosts,
        kafka_security_protocol=p.security_protocol,
        sasl_mechanism=p.sasl_mechanism,
        sasl_user=p.sasl_user,
        sasl_password=p.sasl_password,
        max_request_size=producer_settings.get("max_request_size"),
        compression_type=producer_settings.get("compression_type"),
        producer_settings=producer_settings,
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
    resolved = resolve_profile_name(topic=topic, profile=profile)
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
    resolved = resolve_profile_name(topic=topic, profile=profile)
    producer = _build_async_producer(resolved)
    try:
        yield producer
        await producer.flush()
    finally:
        await producer.close()


async def new_async_producer(
    *,
    profile: Optional[KafkaClusterProfile] = None,
    topic: Optional[str] = None,
) -> _AsyncKafkaProducer:
    """Construct a fresh async producer the caller fully owns.

    For long-lived consumers (e.g. the Temporal logger daemon) where the
    producer outlives any single scope. The caller is responsible for closing
    it. For per-call work prefer `async_producer_scope`.

    This function is async as the underlying producer requires a running
    event loop.
    """
    resolved = resolve_profile_name(topic=topic, profile=profile)
    return _build_async_producer(resolved)


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
