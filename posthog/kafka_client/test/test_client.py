from unittest.mock import patch

from django.test import TestCase, override_settings

import kafka

from posthog.kafka_client.client import _KafkaProducer, build_kafka_consumer


@override_settings(TEST=False)
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

    def test_kafka_default_security_protocol(self):
        producer = _KafkaProducer(test=False)
        self.assertEqual(producer.producer.config["security_protocol"], "PLAINTEXT")  # type: ignore

    @override_settings(
        KAFKA_SECURITY_PROTOCOL="SASL_PLAINTEXT",
        KAFKA_SASL_MECHANISM="<mechanism>",
        KAFKA_SASL_USER="<user>",
        KAFKA_SASL_PASSWORD="<password>",
    )
    def test_kafka_sasl_params(self):
        expected_sasl_config = {
            "security_protocol": "SASL_PLAINTEXT",
            "sasl_mechanism": "<mechanism>",
            "sasl_plain_username": "<user>",
            "sasl_plain_password": "<password>",
        }
        # If an API version isn't specified, the client will immediately attempt to connect to Kafka to determine the
        # version. This will fail, as the dev/test Kafka do not have SASL configured/enabled. Instead, we patch the
        # default client config to specify an API version and skip connecting to Kafka.
        with patch.dict(kafka.KafkaProducer.DEFAULT_CONFIG, {"api_version": (2, 5, 0)}):
            producer = _KafkaProducer(test=False)
        for key, value in expected_sasl_config.items():
            self.assertEqual(value, producer.producer.config[key])  # type: ignore

    @override_settings(
        KAFKA_SECURITY_PROTOCOL="SSL",
        KAFKA_SASL_MECHANISM="<mechanism>",
        KAFKA_SASL_USER="<user>",
        KAFKA_SASL_PASSWORD="<password>",
    )
    def test_kafka_no_sasl_params(self):
        expected_sasl_config = {
            "security_protocol": "SSL",
            "sasl_mechanism": None,
            "sasl_plain_username": None,
            "sasl_plain_password": None,
        }
        with patch.dict(kafka.KafkaProducer.DEFAULT_CONFIG, {"api_version": (2, 5, 0)}):
            producer = _KafkaProducer(test=False)
        for key, value in expected_sasl_config.items():
            self.assertEqual(value, producer.producer.config[key])  # type: ignore
