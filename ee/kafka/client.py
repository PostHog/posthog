from confluent_kafka import Producer

from posthog.settings import KAFKA_HOSTS
from posthog.utils import SingletonDecorator


class KafkaProducer:
    def __init__(self):
        self.producer = Producer({"bootstrap.servers": KAFKA_HOSTS})

    @staticmethod
    def delivery_report(err, msg):
        """ Called once for each message produced to indicate delivery result.
            Triggered by poll() or flush(). """
        if err is not None:
            print("Message delivery failed: {}".format(err))
        else:
            print("Message delivered to {} [{}]".format(msg.topic(), msg.partition()))

    def produce(self, topic, data):
        self.producer.poll(0)
        self.producer.produce(topic, data.encode("utf-8"), callback=self.delivery_report)

    def close(self):
        self.producer.flush()


KafkaProducer = SingletonDecorator(KafkaProducer)
