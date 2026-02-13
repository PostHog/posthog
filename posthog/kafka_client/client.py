import os
import json
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
from kafka import KafkaConsumer as KC
from statshog.defaults.django import statsd
from structlog import get_logger

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client import helper
from posthog.utils import SingletonDecorator

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


class KafkaConsumerForTests:
    def __init__(self, topic="test", max=0, **kwargs):
        self.max = max
        self.n = 0
        self.topic = topic

    def __iter__(self):
        return self

    def __next__(self):
        if self.n <= self.max:
            self.n += 1
            return f"message {self.n} from {self.topic} topic"
        else:
            raise StopIteration

    def seek_to_beginning(self):
        return

    def seek_to_end(self):
        return

    def subscribe(self, _):
        return


class _KafkaSecurityProtocol(StrEnum):
    PLAINTEXT = "PLAINTEXT"
    SSL = "SSL"
    SASL_PLAINTEXT = "SASL_PLAINTEXT"
    SASL_SSL = "SASL_SSL"


def _confluent_sasl_params() -> dict[str, Any]:
    """Return SASL configuration for confluent-kafka."""
    if settings.KAFKA_SECURITY_PROTOCOL in [
        _KafkaSecurityProtocol.SASL_PLAINTEXT,
        _KafkaSecurityProtocol.SASL_SSL,
    ]:
        return {
            "sasl.mechanism": settings.KAFKA_SASL_MECHANISM,
            "sasl.username": settings.KAFKA_SASL_USER,
            "sasl.password": settings.KAFKA_SASL_PASSWORD,
        }
    return {}


def _kafka_python_sasl_params() -> dict[str, Any]:
    """Return SASL configuration for kafka-python (used by consumer)."""
    if settings.KAFKA_SECURITY_PROTOCOL in [
        _KafkaSecurityProtocol.SASL_PLAINTEXT,
        _KafkaSecurityProtocol.SASL_SSL,
    ]:
        return {
            "sasl_mechanism": settings.KAFKA_SASL_MECHANISM,
            "sasl_plain_username": settings.KAFKA_SASL_USER,
            "sasl_plain_password": settings.KAFKA_SASL_PASSWORD,
        }
    return {}


# Mapping from kafka-python style keys to confluent-kafka style keys
_KAFKA_PYTHON_TO_CONFLUENT_KEYS = {
    "client_id": "client.id",
    "metadata_max_age_ms": "metadata.max.age.ms",
    "batch_size": "batch.size",
    "max_request_size": "message.max.bytes",
    "linger_ms": "linger.ms",
    "max_in_flight_requests_per_connection": "max.in.flight.requests.per.connection",
    "buffer_memory": "queue.buffering.max.kbytes",
    "max_block_ms": "queue.buffering.max.ms",
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
        # the default producer uses these defaulted environment variables,
        # but the session recording producer needs to override them
        kafka_base64_keys=None,
        kafka_hosts=None,
        kafka_security_protocol=None,
        max_request_size=None,
        compression_type=None,
    ):
        hostname = os.environ.get("HOSTNAME", "")
        if "temporal-worker-data-warehouse" in hostname:
            import traceback

            logger.info(f"KafkaProducer stack: {traceback.format_stack()}")

        if settings.TEST:
            test = True  # Set at runtime so that overriden settings.TEST is supported
        if kafka_security_protocol is None:
            kafka_security_protocol = settings.KAFKA_SECURITY_PROTOCOL
        if kafka_hosts is None:
            kafka_hosts = settings.KAFKA_HOSTS
        if kafka_base64_keys is None:
            kafka_base64_keys = settings.KAFKA_BASE64_KEYS

        self._test = test

        if test:
            self.producer = KafkaProducerForTests()
        elif kafka_base64_keys:
            self.producer = helper.get_kafka_producer(retries=KAFKA_PRODUCER_RETRIES)
        else:
            config: dict[str, Any] = {
                "bootstrap.servers": ",".join(kafka_hosts) if isinstance(kafka_hosts, list) else kafka_hosts,
                "security.protocol": kafka_security_protocol or _KafkaSecurityProtocol.PLAINTEXT,
                # Wait for leader to acknowledge (matches kafka-python default)
                "acks": 1,
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
                **_confluent_sasl_params(),
                **_convert_kafka_python_settings(settings.KAFKA_PRODUCER_SETTINGS),
            }

            if compression_type:
                config["compression.type"] = compression_type

            if max_request_size:
                config["message.max.bytes"] = max_request_size

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
        headers: Optional[list[tuple[str, str]]] = None,
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
            [(header[0], header[1].encode("utf-8")) for header in headers] if headers is not None else None
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


def can_connect():
    """
    This is intended to validate if we are able to connect to kafka, without
    actually sending any messages. I'm not amazingly pleased with this as a
    solution. Would have liked to have validated that the singleton producer was
    connected. It does expose `bootstrap_connected`, but this becomes false if
    the cluster restarts despite still being able to successfully send messages.

    I'm hoping that the load this generates on the cluster will be
    insignificant, even if it is occuring from, say, 30 separate pods, say,
    every 10 seconds.
    """
    if settings.DEBUG and not settings.TEST:
        return True  # Skip check in development - assume Kafka is "good enough"

    try:
        _KafkaProducer(test=settings.TEST)
    except Exception:
        logger.debug("kafka_connection_failure", exc_info=True)
        return False
    return True


KafkaProducer = SingletonDecorator(_KafkaProducer)
SessionRecordingKafkaProducer = SingletonDecorator(_KafkaProducer)
_WarpStreamKafkaProducer = SingletonDecorator(_KafkaProducer)


def get_warpstream_kafka_producer(
    kafka_hosts: list[str] | str,
    kafka_security_protocol: str,
) -> _KafkaProducer:
    """Get a singleton Kafka producer configured for WarpStream/warehouse pipelines."""
    return _WarpStreamKafkaProducer(
        kafka_hosts=kafka_hosts,
        kafka_security_protocol=kafka_security_protocol,
    )


def session_recording_kafka_producer() -> _KafkaProducer:
    return SessionRecordingKafkaProducer(
        kafka_hosts=settings.SESSION_RECORDING_KAFKA_HOSTS,
        kafka_security_protocol=settings.SESSION_RECORDING_KAFKA_SECURITY_PROTOCOL,
        max_request_size=settings.SESSION_RECORDING_KAFKA_MAX_REQUEST_SIZE_BYTES,
        compression_type="gzip",
    )


def build_kafka_consumer(
    topic: Optional[str],
    value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    auto_offset_reset="latest",
    test=False,
    group_id=None,
    consumer_timeout_ms=5000 if (settings.DEBUG and not settings.TEST) else 305000,
):
    if settings.TEST:
        test = True  # Set at runtime so that overriden settings.TEST is supported
    if test:
        consumer = KafkaConsumerForTests(
            topic=topic,
            auto_offset_reset=auto_offset_reset,
            max=10,
            consumer_timeout_ms=consumer_timeout_ms,
        )
    elif settings.KAFKA_BASE64_KEYS:
        consumer = helper.get_kafka_consumer(
            topic=topic,
            auto_offset_reset=auto_offset_reset,
            value_deserializer=value_deserializer,
            group_id=group_id,
            consumer_timeout_ms=consumer_timeout_ms,
        )
    else:
        consumer = KC(
            bootstrap_servers=settings.KAFKA_HOSTS,
            auto_offset_reset=auto_offset_reset,
            value_deserializer=value_deserializer,
            group_id=group_id,
            consumer_timeout_ms=consumer_timeout_ms,
            security_protocol=settings.KAFKA_SECURITY_PROTOCOL or _KafkaSecurityProtocol.PLAINTEXT,
            **_kafka_python_sasl_params(),
        )
        if topic:
            consumer.subscribe([topic])

    return consumer


class ClickhouseProducer:
    producer: Optional[_KafkaProducer]

    def __init__(self):
        self.producer = KafkaProducer() if not settings.TEST else None

    def produce(self, sql: str, topic: str, data: dict[str, Any], sync: bool = True):
        if self.producer is not None:  # TODO: this should be not sync and
            self.producer.produce(topic=topic, data=data)
        else:
            sync_execute(sql, data)
