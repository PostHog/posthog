"""Kafka cluster profile names.

Isolated module so `posthog.settings.kafka` can import the profile list without
pulling in `kafka_client.client` / `django.conf.settings` (which would create
a circular import at Django settings-load time).
"""

from enum import StrEnum


class KafkaClusterProfile(StrEnum):
    DEFAULT = "default"
    WAREHOUSE_SOURCES = "warehouse_sources"
    CYCLOTRON = "cyclotron"
    INGESTION = "ingestion"
    CALCULATED_EVENTS = "calculated_events"
    SHARED = "shared"
    REPLAY = "replay"
