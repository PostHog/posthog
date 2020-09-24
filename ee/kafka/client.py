import json
from typing import Any, Dict

import kafka_helper  # type: ignore
from kafka import KafkaProducer as KP  # type: ignore

from ee.clickhouse.client import async_execute, sync_execute
from ee.settings import KAFKA_ENABLED
from posthog.settings import IS_HEROKU, KAFKA_HOSTS
from posthog.utils import SingletonDecorator


class _KafkaProducer:
    def __init__(self):
        if not IS_HEROKU:
            self.producer = KP(bootstrap_servers=KAFKA_HOSTS)
        else:
            self.producer = kafka_helper.get_kafka_producer(value_serializer=lambda d: json.dumps(d))

    def produce(self, topic: str, data):
        self.producer.send(topic, data.encode("utf-8"))

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

    def produce(self, sql: str, topic: str, data: Dict[str, Any], sync: bool = True):
        if self.send_to_kafka:
            self.producer.produce(topic=topic, data=data)
        else:
            if sync:
                sync_execute(sql, data)
            else:
                async_execute(sql, data)
