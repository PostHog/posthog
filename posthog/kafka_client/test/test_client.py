from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from posthog.kafka_client.client import _KafkaProducer
from posthog.settings.kafka import KafkaProfileSettings


def _make_profiles(**default_overrides):
    """Build a KAFKA_PROFILES dict for override_settings, with DEFAULT overridden."""

    def make(name, **kwargs):
        base = {
            "name": name,
            "hosts": [],
            "security_protocol": None,
            "sasl_mechanism": None,
            "sasl_user": None,
            "sasl_password": None,
            "producer_settings": {},
        }
        base.update(kwargs)
        return KafkaProfileSettings(**base)

    return {
        "default": make("default", **default_overrides),
        "warehouse_sources": make("warehouse_sources"),
        "cyclotron": make("cyclotron"),
    }


class KafkaConsumerForTests:
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


@override_settings(TEST=False)
class KafkaClientTestCase(TestCase):
    def setUp(self):
        self.topic = "test_topic"
        self.payload = {"foo": "bar"}

    def test_kafka_interface(self):
        producer = _KafkaProducer(test=True)
        consumer = KafkaConsumerForTests(topic=self.topic, test=True)

        producer.produce(topic=self.topic, data="any")
        producer.close()
        msg = next(consumer)
        self.assertEqual(msg, "message 1 from test_topic topic")

    @patch("posthog.kafka_client.client.ConfluentProducer")
    def test_kafka_default_security_protocol(self, mock_producer_class: MagicMock):
        mock_producer_class.return_value = MagicMock()
        _KafkaProducer(test=False)
        config = mock_producer_class.call_args[0][0]
        self.assertEqual(config["security.protocol"], "PLAINTEXT")

    @override_settings(
        KAFKA_PROFILES=_make_profiles(
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="<mechanism>",
            sasl_user="<user>",
            sasl_password="<password>",
        )
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
        KAFKA_PROFILES=_make_profiles(
            security_protocol="SSL",
            sasl_mechanism="<mechanism>",
            sasl_user="<user>",
            sasl_password="<password>",
        )
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

    @override_settings(
        KAFKA_PROFILES=_make_profiles(
            producer_settings={
                "client_id": "my-client",
                "batch_size": 16000000,
                "linger_ms": 100,
                "max_request_size": 6000000,
                "max_in_flight_requests_per_connection": 1000000,
                "buffer_memory": 1073741824,  # 1 GiB, should convert to 1048576 kbytes
                "max_block_ms": 1000,
                "metadata_max_age_ms": 15000,
                "topic_metadata_refresh_interval_ms": 60000,
                "queue_buffering_max_messages": 1000000,
                "sticky_partitioning_linger_ms": 25,
            }
        )
    )
    @patch("posthog.kafka_client.client.ConfluentProducer")
    def test_kafka_producer_settings_flow_to_confluent_config(self, mock_producer_class: MagicMock):
        """Each entry in the DEFAULT profile's producer_settings maps to the expected librdkafka config key."""
        mock_producer_class.return_value = MagicMock()
        _KafkaProducer(test=False)
        config = mock_producer_class.call_args[0][0]
        self.assertEqual(config["client.id"], "my-client")
        self.assertEqual(config["batch.size"], 16000000)
        self.assertEqual(config["linger.ms"], 100)
        self.assertEqual(config["message.max.bytes"], 6000000)
        self.assertEqual(config["max.in.flight.requests.per.connection"], 1000000)
        # buffer_memory is in bytes but confluent expects kbytes.
        self.assertEqual(config["queue.buffering.max.kbytes"], 1048576)
        self.assertEqual(config["queue.buffering.max.ms"], 1000)
        self.assertEqual(config["metadata.max.age.ms"], 15000)
        # Warpstream-friendly tuning knobs wired from the same-named env vars
        # that the Node.js and rust services already use in Helm charts.
        self.assertEqual(config["topic.metadata.refresh.interval.ms"], 60000)
        self.assertEqual(config["queue.buffering.max.messages"], 1000000)
        self.assertEqual(config["sticky.partitioning.linger.ms"], 25)

    @override_settings(KAFKA_PROFILES=_make_profiles(producer_settings={"partitioner": "murmur2_random"}))
    @patch("posthog.kafka_client.client.ConfluentProducer")
    def test_kafka_producer_partitioner_is_dropped(self, mock_producer_class: MagicMock):
        """partitioner is handled differently in confluent-kafka and must not leak through."""
        mock_producer_class.return_value = MagicMock()
        _KafkaProducer(test=False)
        config = mock_producer_class.call_args[0][0]
        self.assertNotIn("partitioner", config)
        self.assertNotIn("partitioner", config.values())

    @override_settings(
        KAFKA_BASE64_KEYS=True,
        KAFKA_PROFILES=_make_profiles(
            security_protocol="SASL_PLAINTEXT",
            sasl_mechanism="<mechanism>",
            sasl_user="<user>",
            sasl_password="<password>",
            producer_settings={"linger_ms": 250, "batch_size": 1_000_000},
        ),
    )
    @patch(
        "posthog.kafka_client.helper.ssl_cert_config",
        return_value={
            "security.protocol": "SSL",
            "ssl.certificate.location": "/tmp/cert.crt",
            "ssl.key.location": "/tmp/key.key",
            "ssl.ca.location": "/tmp/ca.crt",
            "ssl.endpoint.identification.algorithm": "none",
        },
    )
    @patch("posthog.kafka_client.client.ConfluentProducer")
    def test_kafka_base64_keys_merges_ssl_config(self, mock_producer_class: MagicMock, mock_ssl_cert_config: MagicMock):
        """Self-hosted base64 mode overrides security.protocol with SSL and
        adds cert paths, but still honours KAFKA_PRODUCER_SETTINGS tuning."""
        mock_producer_class.return_value = MagicMock()
        _KafkaProducer(test=False)
        config = mock_producer_class.call_args[0][0]

        self.assertEqual(config["security.protocol"], "SSL")
        self.assertEqual(config["ssl.certificate.location"], "/tmp/cert.crt")
        self.assertEqual(config["ssl.key.location"], "/tmp/key.key")
        self.assertEqual(config["ssl.ca.location"], "/tmp/ca.crt")
        self.assertEqual(config["ssl.endpoint.identification.algorithm"], "none")

        # SASL config from the profile must not leak through when SSL certs are active.
        self.assertNotIn("sasl.mechanism", config)

        # Producer settings still flow through — this is what the old helper dropped.
        self.assertEqual(config["linger.ms"], 250)
        self.assertEqual(config["batch.size"], 1_000_000)
