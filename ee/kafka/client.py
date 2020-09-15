import kafka_helper
from kafka import KafkaProducer as KP

from posthog.settings import IS_HEROKU, KAFKA_HOSTS
from posthog.settings import KAFKA_HOSTS
from posthog.utils import SingletonDecorator


class KafkaProducer:
    def __init__(self):
        if not IS_HEROKU:
            self.producer = KP(bootstrap_servers=KAFKA_HOSTS)
        else:
            self.producer = kafka_helper.get_kafka_producer()

    def produce(self, topic: str, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.producer.send(topic, data)

    def close(self):
        self.producer.flush()


KafkaProducer = SingletonDecorator(KafkaProducer)
