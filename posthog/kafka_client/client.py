import json
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import kafka.errors
from kafka import KafkaConsumer as KC
from kafka import KafkaProducer as KP
from kafka.producer.future import FutureProduceResult, RecordMetadata
from kafka.structs import TopicPartition
from statshog.defaults.django import statsd
from structlog import get_logger

from posthog.client import async_execute, sync_execute
from posthog.kafka_client import helper
from posthog.settings import (
    KAFKA_BASE64_KEYS,
    KAFKA_HOSTS,
    KAFKA_SASL_MECHANISM,
    KAFKA_SASL_PASSWORD,
    KAFKA_SASL_USER,
    KAFKA_SECURITY_PROTOCOL,
    TEST,
)
from posthog.utils import SingletonDecorator

KAFKA_PRODUCER_RETRIES = 5

logger = get_logger(__file__)


class TestKafkaProducer:
    def __init__(self):
        pass

    def send(self, topic: str, value: Any, key: Any = None, headers: Optional[List[Tuple[str, bytes]]] = None):
        return FutureProduceResult(topic_partition=TopicPartition(topic, 1))

    def flush(self):
        return


class TestKafkaConsumer:
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


class _KafkaSecurityProtocol(str, Enum):
    PLAINTEXT = "PLAINTEXT"
    SSL = "SSL"
    SASL_PLAINTEXT = "SASL_PLAINTEXT"
    SASL_SSL = "SASL_SSL"


def _sasl_params():
    if KAFKA_SECURITY_PROTOCOL in [_KafkaSecurityProtocol.SASL_PLAINTEXT, _KafkaSecurityProtocol.SASL_SSL]:
        return {
            "sasl_mechanism": KAFKA_SASL_MECHANISM,
            "sasl_plain_username": KAFKA_SASL_USER,
            "sasl_plain_password": KAFKA_SASL_PASSWORD,
        }
    return {}


class _KafkaProducer:
    def __init__(self, test=TEST):
        if test:
            self.producer = TestKafkaProducer()
        elif KAFKA_BASE64_KEYS:
            self.producer = helper.get_kafka_producer(retries=KAFKA_PRODUCER_RETRIES, value_serializer=lambda d: d)
        else:
            self.producer = KP(
                retries=KAFKA_PRODUCER_RETRIES,
                bootstrap_servers=KAFKA_HOSTS,
                security_protocol=KAFKA_SECURITY_PROTOCOL or _KafkaSecurityProtocol.PLAINTEXT,
                **_sasl_params(),
            )

    @staticmethod
    def json_serializer(d):
        b = json.dumps(d).encode("utf-8")
        return b

    def on_send_success(self, record_metadata: RecordMetadata):
        statsd.incr(
            "posthog_cloud_kafka_send_success", tags={"topic": record_metadata.topic,},
        )

    def on_send_failure(self, topic: str, exc: Exception):
        statsd.incr("posthog_cloud_kafka_send_failure", tags={"topic": topic, "exception": exc.__class__.__name__})

    def produce(
        self,
        topic: str,
        data: Any,
        key: Any = None,
        value_serializer: Optional[Callable[[Any], Any]] = None,
        headers: Optional[List[Tuple[str, str]]] = None,
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
    try:
        _KafkaProducer(test=TEST)
    except kafka.errors.KafkaError:
        logger.debug("kafka_connection_failure", exc_info=True)
        return False
    return True


KafkaProducer = SingletonDecorator(_KafkaProducer)


def build_kafka_consumer(
    topic: Optional[str],
    value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    auto_offset_reset="latest",
    test=TEST,
    group_id=None,
    consumer_timeout_ms=float("inf"),
):
    if test:
        consumer = TestKafkaConsumer(
            topic=topic, auto_offset_reset=auto_offset_reset, max=10, consumer_timeout_ms=consumer_timeout_ms
        )
    elif KAFKA_BASE64_KEYS:
        consumer = helper.get_kafka_consumer(
            topic=topic,
            auto_offset_reset=auto_offset_reset,
            value_deserializer=value_deserializer,
            group_id=group_id,
            consumer_timeout_ms=consumer_timeout_ms,
        )
    else:
        consumer = KC(
            bootstrap_servers=KAFKA_HOSTS,
            auto_offset_reset=auto_offset_reset,
            value_deserializer=value_deserializer,
            group_id=group_id,
            consumer_timeout_ms=consumer_timeout_ms,
            security_protocol=KAFKA_SECURITY_PROTOCOL or _KafkaSecurityProtocol.PLAINTEXT,
            **_sasl_params(),
        )
        if topic:
            consumer.subscribe([topic])

    return consumer


class ClickhouseProducer:
    producer: Optional[_KafkaProducer]

    def __init__(self):
        self.producer = KafkaProducer() if not TEST else None

    def produce(self, sql: str, topic: str, data: Dict[str, Any], sync: bool = True):
        if self.producer is not None:
            self.producer.produce(topic=topic, data=data)
        elif sync:
            sync_execute(sql, data)
        else:
            async_execute(sql, data)
