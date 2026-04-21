"""Low-level Kafka primitives.

Most call sites should NOT import from this module directly. The public entry
points for producing are in `posthog.kafka_client.routing`:

* `get_producer(topic=...)` / `producer_scope(topic=...)` for sync producers
* `async_producer_scope(topic=...)` for per-call async producers
* `new_async_producer(topic=...)` for long-lived async producers
"""

import os
import json
import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional

from django.conf import settings

from confluent_kafka import (
    KafkaError,
    KafkaException,
    Message,
    Producer as ConfluentProducer,
)
from confluent_kafka.aio import AIOProducer
from statshog.defaults.django import statsd
from structlog import get_logger

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client import helper

KAFKA_PRODUCER_RETRIES = 5

logger = get_logger(__name__)


@dataclass
class ProduceResult:
    """
    A Future-like wrapper for confluent-kafka delivery results.
    Provides compatibility with code that expects kafka-python style futures.
    """

    topic: str
    _event: threading.Event = field(default_factory=threading.Event)
    _message: Optional[Message] = field(default=None)
    _error: Optional[KafkaError] = field(default=None)

    def set_result(self, error: Optional[KafkaError], message: Optional[Message]):
        """Called by the delivery callback when produce completes."""
        self._error = error
        self._message = message
        self._event.set()

    def get(self, timeout: Optional[float] = None) -> Optional[Message]:
        """
        Wait for the produce to complete and return the result.
        Raises KafkaException if the produce failed.
        """
        if not self._event.wait(timeout=timeout):
            raise TimeoutError("Timeout waiting for produce result")
        if self._error is not None:
            raise KafkaException(self._error)
        return self._message


class KafkaProducerForTests:
    def __init__(self):
        pass

    def produce(
        self,
        topic: str,
        value: bytes,
        key: Optional[bytes] = None,
        headers: Optional[list[tuple[str, str | bytes | None]]] = None,
        on_delivery: Optional[Callable] = None,
    ):
        # Immediately trigger the delivery callback with success
        if on_delivery:
            on_delivery(None, None)

    def poll(self, timeout: float = 0) -> int:
        return 0

    def flush(self, timeout: Optional[float] = None) -> int:
        return 0


class _KafkaSecurityProtocol(StrEnum):
    PLAINTEXT = "PLAINTEXT"
    SSL = "SSL"
    SASL_PLAINTEXT = "SASL_PLAINTEXT"
    SASL_SSL = "SASL_SSL"


def _build_sasl_config(
    security_protocol: Optional[str],
    sasl_mechanism: Optional[str],
    sasl_user: Optional[str],
    sasl_password: Optional[str],
) -> dict[str, Any]:
    """Return confluent-kafka SASL configuration for the given security protocol.

    Empty dict when SASL isn't in use so the keys aren't added to the producer
    config (confluent-kafka rejects SASL keys when the protocol doesn't require
    them).
    """
    if security_protocol in [
        _KafkaSecurityProtocol.SASL_PLAINTEXT,
        _KafkaSecurityProtocol.SASL_SSL,
    ]:
        return {
            "sasl.mechanism": sasl_mechanism,
            "sasl.username": sasl_user,
            "sasl.password": sasl_password,
        }
    return {}


# Mapping from our internal setting key names to confluent-kafka config keys.
# Historically these mirror kafka-python's snake_case API; the three topic/queue/sticky
# entries use confluent's librdkafka names directly since there's no kafka-python analog.
_KAFKA_PYTHON_TO_CONFLUENT_KEYS = {
    "client_id": "client.id",
    "metadata_max_age_ms": "metadata.max.age.ms",
    "batch_size": "batch.size",
    "max_request_size": "message.max.bytes",
    "linger_ms": "linger.ms",
    "max_in_flight_requests_per_connection": "max.in.flight.requests.per.connection",
    "buffer_memory": "queue.buffering.max.kbytes",
    "max_block_ms": "queue.buffering.max.ms",
    "topic_metadata_refresh_interval_ms": "topic.metadata.refresh.interval.ms",
    "queue_buffering_max_messages": "queue.buffering.max.messages",
    "sticky_partitioning_linger_ms": "sticky.partitioning.linger.ms",
    "enable_idempotence": "enable.idempotence",
    "compression_type": "compression.type",
}


def _convert_kafka_python_settings(kafka_python_settings: dict[str, Any]) -> dict[str, Any]:
    """Convert kafka-python style settings to confluent-kafka style."""
    result = {}
    for key, value in kafka_python_settings.items():
        if key in _KAFKA_PYTHON_TO_CONFLUENT_KEYS:
            confluent_key = _KAFKA_PYTHON_TO_CONFLUENT_KEYS[key]
            # buffer_memory is in bytes for kafka-python but kbytes for confluent-kafka
            if key == "buffer_memory":
                value = value // 1024
            result[confluent_key] = value
        elif key == "partitioner":
            # partitioner is handled differently in confluent-kafka, skip it
            pass
        else:
            # Pass through unknown keys as-is (might already be confluent-kafka style)
            result[key] = value
    return result


class _KafkaProducer:
    producer: ConfluentProducer | KafkaProducerForTests
    _test: bool

    def __init__(
        self,
        test=False,
        # The default producer reads from `settings.KAFKA_PROFILES["default"]`,
        # but callers (typically `kafka_client.routing`) can pass a specific
        # profile's hosts/protocol/SASL/producer_settings to target another cluster.
        kafka_base64_keys=None,
        kafka_hosts=None,
        kafka_security_protocol=None,
        sasl_mechanism: Optional[str] = None,
        sasl_user: Optional[str] = None,
        sasl_password: Optional[str] = None,
        max_request_size=None,
        compression_type=None,
        acks: int | str = 1,
        enable_idempotence=False,
        producer_settings: Optional[dict[str, Any]] = None,
    ):
        hostname = os.environ.get("HOSTNAME", "")
        if "temporal-worker-data-warehouse" in hostname:
            import traceback

            logger.info(f"KafkaProducer stack: {traceback.format_stack()}")

        if settings.TEST:
            test = True  # Set at runtime so that overriden settings.TEST is supported
        default_profile = settings.KAFKA_PROFILES["default"]
        if kafka_security_protocol is None:
            kafka_security_protocol = default_profile.security_protocol
        if kafka_hosts is None:
            kafka_hosts = default_profile.hosts
        if kafka_base64_keys is None:
            kafka_base64_keys = settings.KAFKA_BASE64_KEYS
        # Self-hosted base64 cert mode provides its own SSL material; force the
        # protocol to SSL before SASL resolution so SASL creds aren't attached.
        if kafka_base64_keys:
            kafka_security_protocol = _KafkaSecurityProtocol.SSL
        if sasl_mechanism is None:
            sasl_mechanism = default_profile.sasl_mechanism
        if sasl_user is None:
            sasl_user = default_profile.sasl_user
        if sasl_password is None:
            sasl_password = default_profile.sasl_password
        resolved_producer_settings: dict[str, Any] = (
            producer_settings if producer_settings is not None else default_profile.producer_settings
        )

        self._test = test

        if test:
            self.producer = KafkaProducerForTests()
        else:
            config: dict[str, Any] = {
                "bootstrap.servers": ",".join(kafka_hosts) if isinstance(kafka_hosts, list) else kafka_hosts,
                "security.protocol": kafka_security_protocol or _KafkaSecurityProtocol.PLAINTEXT,
                # Wait for leader to acknowledge (matches kafka-python default)
                "acks": acks,
                # Retry configuration
                "message.send.max.retries": KAFKA_PRODUCER_RETRIES,
                "retry.backoff.ms": 100,
                # Connection management - recycle idle connections before NAT Gateway/NLB kills them (350s timeout)
                "connections.max.idle.ms": 60000,  # 1 minute
                "reconnect.backoff.ms": 50,
                "reconnect.backoff.max.ms": 1000,
                # Socket timeout for connection establishment
                "socket.timeout.ms": 60000,
                # Request timeout
                "request.timeout.ms": 30000,
                # Explicit API version to avoid slow auto-detection
                "api.version.request": True,
                "broker.version.fallback": "2.8.0",
                # Enable TCP keepalive
                "socket.keepalive.enable": True,
                # Delivery report callback will be called for all messages
                "delivery.report.only.error": False,
                **_build_sasl_config(kafka_security_protocol, sasl_mechanism, sasl_user, sasl_password),
                **_convert_kafka_python_settings(resolved_producer_settings),
            }

            if compression_type:
                config["compression.type"] = compression_type

            if max_request_size:
                config["message.max.bytes"] = max_request_size

            if enable_idempotence:
                config["enable.idempotence"] = enable_idempotence
                # Idempotence requires acks=all, override if necessary
                if config["acks"] != "all":
                    config["acks"] = "all"

            if kafka_base64_keys:
                # Writes cert/key/CA files on first call; returns the ssl.* paths
                # plus a redundant security.protocol=SSL (already set above).
                config.update(helper.ssl_cert_config())

            self.producer = ConfluentProducer(config)

    @staticmethod
    def json_serializer(d):
        b = json.dumps(d).encode("utf-8")
        return b

    def _on_delivery(self, topic: str, result: ProduceResult, err: Optional[KafkaError], msg: Message):
        """Delivery callback for confluent-kafka."""
        result.set_result(err, msg)
        if err is not None:
            statsd.incr(
                "posthog_cloud_kafka_send_failure",
                tags={"topic": topic, "exception": err.name()},
            )
        else:
            statsd.incr(
                "posthog_cloud_kafka_send_success",
                tags={"topic": msg.topic() if msg else None},
            )

    def produce(
        self,
        topic: str,
        data: Any,
        key: Any = None,
        value_serializer: Optional[Callable[[Any], Any]] = None,
        headers: Optional[list[tuple[str, str | bytes]]] = None,
    ) -> ProduceResult:
        if not value_serializer:
            value_serializer = self.json_serializer
        b = value_serializer(data)
        if key is not None:
            if isinstance(key, bytes):
                pass  # already bytes
            else:
                key = str(key).encode("utf-8")
        encoded_headers: list[tuple[str, str | bytes | None]] | None = (
            [(h[0], h[1] if isinstance(h[1], bytes) else h[1].encode("utf-8")) for h in headers]
            if headers is not None
            else None
        )

        result = ProduceResult(topic=topic)

        if self._test:
            self.producer.produce(topic, value=b, key=key, headers=encoded_headers)
            result.set_result(None, None)
        else:
            self.producer.produce(
                topic,
                value=b,
                key=key,
                headers=encoded_headers,
                on_delivery=lambda err, msg: self._on_delivery(topic, result, err, msg),
            )
            # Poll to trigger any pending delivery callbacks (non-blocking)
            self.producer.poll(0)

        return result

    def flush(self, timeout: Optional[float] = None):
        if timeout is not None:
            self.producer.flush(timeout)
        else:
            self.producer.flush()

    def close(self):
        self.producer.flush()


class _AsyncKafkaProducer:
    producer: AIOProducer
    _closed: bool

    def __init__(
        self,
        kafka_hosts: list[str] | str | None = None,
        kafka_security_protocol: str | None = None,
        sasl_mechanism: Optional[str] = None,
        sasl_user: Optional[str] = None,
        sasl_password: Optional[str] = None,
        max_request_size: int | None = None,
        compression_type: str | None = None,
        producer_settings: Optional[dict[str, Any]] = None,
    ):
        default_profile = settings.KAFKA_PROFILES["default"]
        if kafka_security_protocol is None:
            kafka_security_protocol = default_profile.security_protocol
        if kafka_hosts is None:
            kafka_hosts = default_profile.hosts
        if sasl_mechanism is None:
            sasl_mechanism = default_profile.sasl_mechanism
        if sasl_user is None:
            sasl_user = default_profile.sasl_user
        if sasl_password is None:
            sasl_password = default_profile.sasl_password
        resolved_producer_settings: dict[str, Any] = (
            producer_settings if producer_settings is not None else default_profile.producer_settings
        )

        config: dict[str, Any] = {
            "bootstrap.servers": ",".join(kafka_hosts) if isinstance(kafka_hosts, list) else kafka_hosts,
            "security.protocol": kafka_security_protocol or _KafkaSecurityProtocol.PLAINTEXT,
            "acks": 1,
            "message.send.max.retries": KAFKA_PRODUCER_RETRIES,
            "retry.backoff.ms": 100,
            "connections.max.idle.ms": 60000,
            "reconnect.backoff.ms": 50,
            "reconnect.backoff.max.ms": 1000,
            "socket.timeout.ms": 60000,
            "request.timeout.ms": 30000,
            "api.version.request": True,
            "broker.version.fallback": "2.8.0",
            "socket.keepalive.enable": True,
            **_build_sasl_config(kafka_security_protocol, sasl_mechanism, sasl_user, sasl_password),
            **_convert_kafka_python_settings(resolved_producer_settings),
        }

        if compression_type:
            config["compression.type"] = compression_type

        if max_request_size:
            config["message.max.bytes"] = max_request_size

        self.producer = AIOProducer(config)
        self._closed = False

    @staticmethod
    def json_serializer(d: Any) -> bytes:
        return json.dumps(d).encode("utf-8")

    async def produce(
        self,
        topic: str,
        data: Any,
        key: Any = None,
        value_serializer: Callable[[Any], Any] | None = None,
        headers: list[tuple[str, str | bytes]] | None = None,
    ) -> asyncio.Future[Any]:
        if not value_serializer:
            value_serializer = self.json_serializer
        b = value_serializer(data)
        if key is not None:
            if not isinstance(key, bytes):
                key = str(key).encode("utf-8")
        encoded_headers: list[tuple[str, str | bytes | None]] | None = (
            [(h[0], h[1] if isinstance(h[1], bytes) else h[1].encode("utf-8")) for h in headers]
            if headers is not None
            else None
        )

        future = await self.producer.produce(
            topic=topic,
            value=b,
            key=key,
            headers=encoded_headers,
        )
        return future

    async def flush(self, timeout: float | None = None) -> None:
        if timeout is not None:
            await self.producer.flush(timeout)
        else:
            await self.producer.flush()

    async def close(self) -> None:
        if not self._closed:
            await self.producer.close()
            self._closed = True


class ClickhouseProducer:
    """Writes a row to ClickHouse via Kafka in production, or directly via SQL in tests.

    The Kafka producer is resolved per-call via the routing module so each topic
    can target the cluster mapped in TOPIC_ROUTING.
    """

    def produce(self, sql: str, topic: str, data: dict[str, Any]):
        if settings.TEST:
            sync_execute(sql, data)
            return
        # Lazy import: routing imports from this module.
        from posthog.kafka_client.routing import get_producer

        get_producer(topic=topic).produce(topic=topic, data=data)
