"""Kafka settings, resolved per-cluster-profile.

Each `KafkaClusterProfile` gets its own env var namespace — `KAFKA_<PROFILE>_*` —
for hosts, security, SASL, and producer tuning. When a profile-specific value is
unset, resolution falls back to `KAFKA_DEFAULT_*`, then to built-in defaults.

Legacy env var names (e.g. `KAFKA_HOSTS`, `WAREHOUSE_PIPELINES_KAFKA_HOSTS`) are
still honoured so existing Helm charts keep working without edits. New-format
names always win if both are set.

Consumers should use `settings.KAFKA_PROFILES[profile.value]` to get a fully
resolved `KafkaProfileSettings`; `posthog.kafka_client.routing` does exactly that.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

from posthog.kafka_client.profiles import KafkaClusterProfile
from posthog.settings.utils import get_from_env, str_to_bool


def _parse_kafka_hosts(hosts_string: str) -> list[str]:
    hosts = []
    for host in (hosts_string or "").split(","):
        if "://" in host:
            hosts.append(urlparse(host).netloc)
        else:
            hosts.append(host)
    return [host for host in hosts if host]


# ---------------------------------------------------------------------------
# Per-profile env resolution
# ---------------------------------------------------------------------------

# Legacy env-var names registered per (profile, suffix). Read when the
# corresponding new-format name isn't set.
_LEGACY_PROFILE_ENVS: dict[tuple[str, str], tuple[str, ...]] = {
    # DEFAULT profile: legacy names that predate the KAFKA_DEFAULT_* convention.
    ("default", "HOSTS"): ("KAFKA_HOSTS", "KAFKA_URL"),
    ("default", "SECURITY_PROTOCOL"): ("KAFKA_SECURITY_PROTOCOL",),
    ("default", "SASL_MECHANISM"): ("KAFKA_SASL_MECHANISM",),
    ("default", "SASL_USER"): ("KAFKA_SASL_USER",),
    ("default", "SASL_PASSWORD"): ("KAFKA_SASL_PASSWORD",),
    ("default", "PRODUCER_CLIENT_ID"): ("KAFKA_PRODUCER_CLIENT_ID",),
    ("default", "PRODUCER_METADATA_MAX_AGE_MS"): ("KAFKA_PRODUCER_METADATA_MAX_AGE_MS",),
    ("default", "PRODUCER_BATCH_SIZE"): ("KAFKA_PRODUCER_BATCH_SIZE",),
    ("default", "PRODUCER_MAX_REQUEST_SIZE"): ("KAFKA_PRODUCER_MAX_REQUEST_SIZE",),
    ("default", "PRODUCER_LINGER_MS"): ("KAFKA_PRODUCER_LINGER_MS",),
    ("default", "PRODUCER_PARTITIONER"): ("KAFKA_PRODUCER_PARTITIONER",),
    ("default", "PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION"): (
        "KAFKA_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION",
    ),
    ("default", "PRODUCER_BUFFER_MEMORY"): ("KAFKA_PRODUCER_BUFFER_MEMORY",),
    ("default", "PRODUCER_MAX_BLOCK_MS"): ("KAFKA_PRODUCER_MAX_BLOCK_MS",),
    ("default", "PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS"): ("KAFKA_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS",),
    ("default", "PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES"): ("KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES",),
    ("default", "PRODUCER_STICKY_PARTITIONING_LINGER_MS"): ("KAFKA_PRODUCER_STICKY_PARTITIONING_LINGER_MS",),
    # WAREHOUSE_SOURCES profile legacy names.
    ("warehouse_sources", "HOSTS"): ("WAREHOUSE_PIPELINES_KAFKA_HOSTS",),
    ("warehouse_sources", "SECURITY_PROTOCOL"): ("WAREHOUSE_PIPELINES_KAFKA_SECURITY_PROTOCOL",),
    # CYCLOTRON profile legacy names.
    ("cyclotron", "HOSTS"): ("KAFKA_CYCLOTRON_WARPSTREAM_HOSTS",),
    ("cyclotron", "SECURITY_PROTOCOL"): ("KAFKA_CYCLOTRON_WARPSTREAM_PROTOCOL",),
}


def _env_for(profile: str, suffix: str) -> Optional[str]:
    """Resolve a single env value through the per-profile fallback chain.

    Order:
    1. `KAFKA_<PROFILE>_<SUFFIX>`
    2. Legacy aliases registered for that (profile, suffix)
    3. `KAFKA_DEFAULT_<SUFFIX>` (skipped when profile is already "default")
    4. Legacy aliases registered for ("default", suffix)
    Returns None if nothing is set — caller applies its own default.
    """
    # 1: Profile-specific new name.
    if (val := os.getenv(f"KAFKA_{profile.upper()}_{suffix}")) not in (None, ""):
        return val
    # 2: Profile-specific legacy names.
    for legacy in _LEGACY_PROFILE_ENVS.get((profile, suffix), ()):
        if (val := os.getenv(legacy)) not in (None, ""):
            return val
    if profile == "default":
        return None
    # 3: Default-profile new name.
    if (val := os.getenv(f"KAFKA_DEFAULT_{suffix}")) not in (None, ""):
        return val
    # 4: Default-profile legacy names.
    for legacy in _LEGACY_PROFILE_ENVS.get(("default", suffix), ()):
        if (val := os.getenv(legacy)) not in (None, ""):
            return val
    return None


def _env_int(profile: str, suffix: str) -> Optional[int]:
    val = _env_for(profile, suffix)
    return int(val) if val is not None else None


def _env_bool(profile: str, suffix: str) -> Optional[bool]:
    val = _env_for(profile, suffix)
    return str_to_bool(val) if val is not None else None


# ---------------------------------------------------------------------------
# Producer settings assembly
# ---------------------------------------------------------------------------

# Code-level producer defaults, per profile. Any env value (profile-specific or
# default) wins over these. Keep entries minimal — the goal is "sane behaviour
# without any env vars" not "optimal tuning".
_PROFILE_PRODUCER_DEFAULTS: dict[str, dict[str, Any]] = {
    "default": {},
    "warehouse_sources": {
        # Warehouse pipeline needs exactly-once delivery.
        "acks": "all",
        "enable_idempotence": True,
    },
    "cyclotron": {},
}


# Environment-sourced producer tuning (snake_case keys, consumed by
# _convert_kafka_python_settings in client.py).
_PRODUCER_ENV_SUFFIXES_INT = [
    ("metadata_max_age_ms", "PRODUCER_METADATA_MAX_AGE_MS"),
    ("batch_size", "PRODUCER_BATCH_SIZE"),
    ("max_request_size", "PRODUCER_MAX_REQUEST_SIZE"),
    ("linger_ms", "PRODUCER_LINGER_MS"),
    ("max_in_flight_requests_per_connection", "PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION"),
    ("buffer_memory", "PRODUCER_BUFFER_MEMORY"),
    ("max_block_ms", "PRODUCER_MAX_BLOCK_MS"),
    ("topic_metadata_refresh_interval_ms", "PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS"),
    ("queue_buffering_max_messages", "PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES"),
    ("sticky_partitioning_linger_ms", "PRODUCER_STICKY_PARTITIONING_LINGER_MS"),
]
_PRODUCER_ENV_SUFFIXES_STR = [
    ("client_id", "PRODUCER_CLIENT_ID"),
    ("partitioner", "PRODUCER_PARTITIONER"),
    ("compression_type", "PRODUCER_COMPRESSION_TYPE"),
]


def _resolve_producer_settings(profile: str) -> dict[str, Any]:
    """Layer env-set producer tuning on top of the profile's code defaults.

    Returned dict uses snake_case keys; `_convert_kafka_python_settings` in
    `kafka_client.client` translates them to librdkafka dot notation.
    """
    merged: dict[str, Any] = dict(_PROFILE_PRODUCER_DEFAULTS.get(profile, {}))
    for key, suffix in _PRODUCER_ENV_SUFFIXES_INT:
        if (value := _env_int(profile, suffix)) is not None:
            merged[key] = value
    for key, suffix in _PRODUCER_ENV_SUFFIXES_STR:
        if (value := _env_for(profile, suffix)) is not None:
            merged[key] = value
    # acks / enable_idempotence have typed resolution.
    if (acks := _env_for(profile, "PRODUCER_ACKS")) is not None:
        merged["acks"] = int(acks) if acks.isdigit() else acks
    if (idempotence := _env_bool(profile, "PRODUCER_ENABLE_IDEMPOTENCE")) is not None:
        merged["enable_idempotence"] = idempotence
    return merged


# ---------------------------------------------------------------------------
# KafkaProfileSettings + KAFKA_PROFILES map
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KafkaProfileSettings:
    """Fully resolved settings for one Kafka cluster profile."""

    name: str
    hosts: list[str]
    security_protocol: Optional[str]
    sasl_mechanism: Optional[str]
    sasl_user: Optional[str]
    sasl_password: Optional[str]
    producer_settings: dict[str, Any] = field(default_factory=dict)


def _resolve_profile(profile: str) -> KafkaProfileSettings:
    hosts_raw = _env_for(profile, "HOSTS") or ("kafka:9092" if profile == "default" else "")
    return KafkaProfileSettings(
        name=profile,
        hosts=_parse_kafka_hosts(hosts_raw),
        security_protocol=_env_for(profile, "SECURITY_PROTOCOL"),
        sasl_mechanism=_env_for(profile, "SASL_MECHANISM"),
        sasl_user=_env_for(profile, "SASL_USER"),
        sasl_password=_env_for(profile, "SASL_PASSWORD"),
        producer_settings=_resolve_producer_settings(profile),
    )


KAFKA_PROFILES: dict[str, KafkaProfileSettings] = {
    profile.value: _resolve_profile(profile.value) for profile in KafkaClusterProfile
}


# ---------------------------------------------------------------------------
# Back-compat shims
#
# Existing code paths (CH migrations, temporal workers, kafka_client.client)
# still read `settings.KAFKA_HOSTS`, `settings.KAFKA_SECURITY_PROTOCOL`, etc.
# These mirror the DEFAULT profile; the legacy-named profile overrides mirror
# their new KAFKA_<PROFILE>_* equivalents.
# ---------------------------------------------------------------------------

_default = KAFKA_PROFILES[KafkaClusterProfile.DEFAULT.value]
_warehouse = KAFKA_PROFILES[KafkaClusterProfile.WAREHOUSE_SOURCES.value]
_cyclotron = KAFKA_PROFILES[KafkaClusterProfile.CYCLOTRON.value]

KAFKA_HOSTS: list[str] = _default.hosts
KAFKA_SECURITY_PROTOCOL: Optional[str] = _default.security_protocol
KAFKA_SASL_MECHANISM: Optional[str] = _default.sasl_mechanism
KAFKA_SASL_USER: Optional[str] = _default.sasl_user
KAFKA_SASL_PASSWORD: Optional[str] = _default.sasl_password
KAFKA_PRODUCER_SETTINGS: dict[str, Any] = _default.producer_settings

WAREHOUSE_PIPELINES_KAFKA_HOSTS: list[str] = _warehouse.hosts
WAREHOUSE_PIPELINES_KAFKA_SECURITY_PROTOCOL: Optional[str] = _warehouse.security_protocol

KAFKA_CYCLOTRON_WARPSTREAM_HOSTS: list[str] = _cyclotron.hosts
KAFKA_CYCLOTRON_WARPSTREAM_PROTOCOL: Optional[str] = _cyclotron.security_protocol

# Misc Kafka settings that don't vary per profile.
KAFKA_PREFIX: str = os.getenv("KAFKA_PREFIX", "")
KAFKA_BASE64_KEYS: bool = get_from_env("KAFKA_BASE64_KEYS", False, type_cast=str_to_bool)
KAFKA_HOSTS_FOR_CLICKHOUSE: list[str] = _parse_kafka_hosts(os.getenv("KAFKA_URL_FOR_CLICKHOUSE", "")) or KAFKA_HOSTS

# Per-topic overrides for the kafka_client.routing map. Comma-separated
# "topic=profile" entries; merged over the code-level defaults at lookup time.
# Example: "clickhouse_precalculated_person_properties=warpstream_calculated_events"
KAFKA_TOPIC_ROUTING_OVERRIDES: str = os.getenv("KAFKA_TOPIC_ROUTING_OVERRIDES", "") or ""
