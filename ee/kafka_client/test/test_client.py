from django.test import TestCase

from ee.kafka_client.client import build_kafka_consumer, _KafkaProducer


class KafkaClientTestCase(TestCase):
    def setUp(self):
        self.topic = "test_topic"
        self.payload = {"foo": "bar"}

        self.producer = _KafkaProducer(test=False)
        self.consumer = build_kafka_consumer(topic=self.topic, auto_offset_reset="earliest", test=False)

    def test_kafka_interface(self):
        producer = _KafkaProducer(test=True)
        consumer = build_kafka_consumer(topic=self.topic, test=True)

        producer.produce(topic=self.topic, data="any")
        producer.close()
        msg = next(consumer)
        self.assertEqual(msg, "message 1 from test_topic topic")

    def test_kafka_produce(self):
        self.producer.produce(topic=self.topic, data=self.payload)
        self.producer.close()

    def test_kafka_produce_and_consume(self):
        self.producer.produce(topic=self.topic, data=self.payload)
        payload = next(self.consumer)
        self.assertEqual(payload.value, self.payload)
