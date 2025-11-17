import json
from collections.abc import Callable
from enum import StrEnum
from typing import Any, Optional

from django.conf import settings

from kafka import (
    KafkaConsumer as KC,
    KafkaProducer as KP,
)
from kafka.producer.future import FutureProduceResult, FutureRecordMetadata, RecordMetadata
from kafka.structs import TopicPartition
from statshog.defaults.django import statsd
from structlog import get_logger

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client import helper
from posthog.utils import SingletonDecorator

KAFKA_PRODUCER_RETRIES = 5

logger = get_logger(__name__)


class KafkaProducerForTests:
    def __init__(self):
        pass

    def send(
        self,
        topic: str,
        value: Any,
        key: Any = None,
        headers: Optional[list[tuple[str, bytes]]] = None,
    ):
        produce_future = FutureProduceResult(topic_partition=TopicPartition(topic, 1))
        future = FutureRecordMetadata(
            produce_future=produce_future,
            relative_offset=0,
            timestamp_ms=0,
            checksum=0,
            serialized_key_size=0,
            serialized_value_size=0,
            serialized_header_size=0,
        )

        # NOTE: this is probably not the right response, but should do for now
        # until we actually start using the response. At the time of writing we
        # only use the future to reraising on error.
        produce_future.success(None)
        future.success(None)
        return future

    def flush(self, timeout=None):
        return


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


def _sasl_params():
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


class _KafkaProducer:
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
        if settings.TEST:
            test = True  # Set at runtime so that overriden settings.TEST is supported
        if kafka_security_protocol is None:
            kafka_security_protocol = settings.KAFKA_SECURITY_PROTOCOL
        if kafka_hosts is None:
            kafka_hosts = settings.KAFKA_HOSTS
        if kafka_base64_keys is None:
            kafka_base64_keys = settings.KAFKA_BASE64_KEYS

        if test:
            self.producer = KafkaProducerForTests()
        elif kafka_base64_keys:
            self.producer = helper.get_kafka_producer(retries=KAFKA_PRODUCER_RETRIES, value_serializer=lambda d: d)
        else:
            self.producer = KP(
                retries=KAFKA_PRODUCER_RETRIES,
                bootstrap_servers=kafka_hosts,
                security_protocol=kafka_security_protocol or _KafkaSecurityProtocol.PLAINTEXT,
                compression_type=compression_type,
                **{"max_request_size": max_request_size} if max_request_size else {},
                **{"api_version_auto_timeout_ms": 30000}
                if settings.DEBUG
                else {},  # Local development connections could be really slow
                **settings.KAFKA_PRODUCER_SETTINGS,
                **_sasl_params(),
            )

    @staticmethod
    def json_serializer(d):
        b = json.dumps(d).encode("utf-8")
        return b

    def on_send_success(self, record_metadata: RecordMetadata):
        statsd.incr(
            "posthog_cloud_kafka_send_success", tags={"topic": record_metadata.topic if record_metadata else None}
        )

    def on_send_failure(self, topic: str, exc: Exception):
        statsd.incr(
            "posthog_cloud_kafka_send_failure",
            tags={"topic": topic, "exception": exc.__class__.__name__},
        )

    def produce(
        self,
        topic: str,
        data: Any,
        key: Any = None,
        value_serializer: Optional[Callable[[Any], Any]] = None,
        headers: Optional[list[tuple[str, str]]] = None,
    ):
        if not value_serializer:
            value_serializer = self.json_serializer
        b = value_serializer(data)
        if key is not None:
            key = key.encode("utf-8")
        encoded_headers = (
            [(header[0], header[1].encode("utf-8")) for header in headers] if headers is not None else None
        )
        future = self.producer.send(topic, value=b, key=key, headers=encoded_headers)
        # Record if the send request was successful or not
        future.add_callback(self.on_send_success).add_errback(lambda exc: self.on_send_failure(topic=topic, exc=exc))
        return future

    def flush(self, timeout=None):
        self.producer.flush(timeout)

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
            **_sasl_params(),
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
