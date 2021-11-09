import io
import json
from typing import Any, Callable, Dict, Optional

from google.protobuf.internal.encoder import _VarintBytes  # type: ignore
from google.protobuf.json_format import MessageToJson
from kafka import KafkaConsumer as KC
from kafka import KafkaProducer as KP

from ee.clickhouse.client import async_execute, sync_execute
from ee.kafka_client import helper
from ee.settings import KAFKA_ENABLED
from posthog.settings import KAFKA_BASE64_KEYS, KAFKA_HOSTS, TEST
from posthog.utils import SingletonDecorator

KAFKA_PRODUCER_RETRIES = 5


class TestKafkaProducer:
    def __init__(self):
        pass

    def send(self, topic: str, value: Any, key: Any = None):
        return

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


class _KafkaProducer:
    def __init__(self, test=TEST):
        if test:
            self.producer = TestKafkaProducer()
        elif KAFKA_BASE64_KEYS:
            self.producer = helper.get_kafka_producer(retries=KAFKA_PRODUCER_RETRIES, value_serializer=lambda d: d)
        else:
            self.producer = KP(retries=KAFKA_PRODUCER_RETRIES, bootstrap_servers=KAFKA_HOSTS)

    @staticmethod
    def json_serializer(d):
        b = json.dumps(d).encode("utf-8")
        return b

    def produce(self, topic: str, data: Any, key: Any = None, value_serializer: Optional[Callable[[Any], Any]] = None):
        if not value_serializer:
            value_serializer = self.json_serializer
        b = value_serializer(data)
        if key is not None:
            key = key.encode("utf-8")
        self.producer.send(topic, value=b)

    def close(self):
        self.producer.flush()


KafkaProducer = SingletonDecorator(_KafkaProducer)


def build_kafka_consumer(
    topic: str, value_deserializer=lambda v: json.loads(v.decode("utf-8")), auto_offset_reset="latest", test=TEST
):
    if test:
        consumer = TestKafkaConsumer(topic=topic, auto_offset_reset=auto_offset_reset, max=10)
    elif KAFKA_BASE64_KEYS:
        consumer = helper.get_kafka_consumer(
            topic=topic, auto_offset_reset=auto_offset_reset, value_deserializer=value_deserializer
        )
    else:
        consumer = KC(
            topic,
            bootstrap_servers=KAFKA_HOSTS,
            auto_offset_reset=auto_offset_reset,
            value_deserializer=value_deserializer,
        )
    return consumer


class ClickhouseProducer:
    def __init__(self, kafka_enabled=KAFKA_ENABLED):
        if kafka_enabled:
            self.send_to_kafka = True
            self.producer = KafkaProducer()
        else:
            self.send_to_kafka = False

    @staticmethod
    def proto_length_serializer(data: Any) -> bytes:
        f = io.BytesIO()
        f.write(_VarintBytes(data.ByteSize()))
        f.write(data.SerializeToString())
        f.seek(0)
        return f.read()

    def produce_proto(self, sql: str, topic: str, data: Any, sync: bool = True):
        if self.send_to_kafka:
            self.producer.produce(topic=topic, data=data, value_serializer=self.proto_length_serializer)
        else:
            dict_data = json.loads(
                MessageToJson(data, including_default_value_fields=True, preserving_proto_field_name=True)
            )
            if sync:
                sync_execute(sql, dict_data)
            else:
                async_execute(sql, dict_data)

    def produce(self, sql: str, topic: str, data: Dict[str, Any], sync: bool = True):
        if self.send_to_kafka:
            self.producer.produce(topic=topic, data=data)
        else:
            if sync:
                sync_execute(sql, data)
            else:
                async_execute(sql, data)
