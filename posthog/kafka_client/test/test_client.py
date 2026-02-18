from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

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

    @patch("posthog.kafka_client.client.ConfluentProducer")
    def test_kafka_default_security_protocol(self, mock_producer_class: MagicMock):
        mock_producer_class.return_value = MagicMock()
        _KafkaProducer(test=False)
        config = mock_producer_class.call_args[0][0]
        self.assertEqual(config["security.protocol"], "PLAINTEXT")

    @override_settings(
        KAFKA_SECURITY_PROTOCOL="SASL_PLAINTEXT",
        KAFKA_SASL_MECHANISM="<mechanism>",
        KAFKA_SASL_USER="<user>",
        KAFKA_SASL_PASSWORD="<password>",
    )
    @patch("posthog.kafka_client.client.ConfluentProducer")
    def test_kafka_sasl_params(self, mock_producer_class: MagicMock):
        mock_producer_class.return_value = MagicMock()
        _KafkaProducer(test=False)
        config = mock_producer_class.call_args[0][0]
        self.assertEqual(config["security.protocol"], "SASL_PLAINTEXT")
        self.assertEqual(config["sasl.mechanism"], "<mechanism>")
        self.assertEqual(config["sasl.username"], "<user>")
        self.assertEqual(config["sasl.password"], "<password>")

    @override_settings(
        KAFKA_SECURITY_PROTOCOL="SSL",
        KAFKA_SASL_MECHANISM="<mechanism>",
        KAFKA_SASL_USER="<user>",
        KAFKA_SASL_PASSWORD="<password>",
    )
    @patch("posthog.kafka_client.client.ConfluentProducer")
    def test_kafka_no_sasl_params(self, mock_producer_class: MagicMock):
        mock_producer_class.return_value = MagicMock()
        _KafkaProducer(test=False)
        config = mock_producer_class.call_args[0][0]
        self.assertEqual(config["security.protocol"], "SSL")
        # SASL params should not be present when using SSL without SASL
        self.assertNotIn("sasl.mechanism", config)
        self.assertNotIn("sasl.username", config)
        self.assertNotIn("sasl.password", config)
