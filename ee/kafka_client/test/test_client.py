from django.test import TestCase

from ee.kafka_client.client import _KafkaProducer, build_kafka_consumer


class KafkaClientTestCase(TestCase):
    def setUp(self):
        self.topic = "test_topic"
        self.payload = {"foo": "bar"}

    def test_kafka_interface(self):
        producer = _KafkaProducer(test=True)
        consumer = build_kafka_consumer(topic=self.topic, test=True)

        producer.produce(topic=self.topic, data="any")
        producer.close()
        msg = next(consumer)
        self.assertEqual(msg, "message 1 from test_topic topic")

    def test_kafka_produce(self):
        producer = _KafkaProducer(test=False)
        producer.produce(topic=self.topic, data=self.payload)
        producer.close()

    def test_kafka_produce_and_consume(self):
        producer = _KafkaProducer(test=False)
        consumer = build_kafka_consumer(topic=self.topic, auto_offset_reset="earliest", test=False)
        producer.produce(topic=self.topic, data=self.payload)
        payload = next(consumer)
        self.assertEqual(payload.value, self.payload)
