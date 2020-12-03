import io
import json
from typing import Any, Callable, Dict, Optional

import kafka_helper
from google.protobuf.internal.encoder import _VarintBytes  # type: ignore
from google.protobuf.json_format import MessageToJson
from kafka import KafkaProducer as KP

from ee.clickhouse.client import async_execute, sync_execute
from ee.kafka_client import helper
from ee.settings import KAFKA_ENABLED
from posthog.settings import IS_HEROKU, KAFKA_BASE64_KEYS, KAFKA_HOSTS, TEST
from posthog.utils import SingletonDecorator


class TestKafkaProducer:
    def __init__(self):
        pass

    def send(self, topic: str, data: Any):
        return

    def flush(self):
        return


class _KafkaProducer:
    def __init__(self):
        if TEST:
            self.producer = TestKafkaProducer()
        elif IS_HEROKU:
            self.producer = kafka_helper.get_kafka_producer(value_serializer=lambda d: d)
        elif KAFKA_BASE64_KEYS:
            self.producer = helper.get_kafka_producer(value_serializer=lambda d: d)
        else:
            self.producer = KP(bootstrap_servers=KAFKA_HOSTS)

    @staticmethod
    def json_serializer(d):
        b = json.dumps(d).encode("utf-8")
        return b

    def produce(self, topic: str, data: Any, value_serializer: Optional[Callable[[Any], Any]] = None):
        if not value_serializer:
            value_serializer = self.json_serializer
        b = value_serializer(data)
        self.producer.send(topic, b)

    def close(self):
        self.producer.flush()


KafkaProducer = SingletonDecorator(_KafkaProducer)


class ClickhouseProducer:
    def __init__(self):
        if KAFKA_ENABLED:
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
