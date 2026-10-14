from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.kafka_engine import kafka_engine


class TestKafkaEngine(SimpleTestCase):
    @parameterized.expand(
        [
            ("without_schema", None, "kafka_format = 'JSONEachRow')"),
            (
                "with_schema",
                "personhog/types/v1/person.proto:Person",
                "kafka_format = 'ProtobufSingle', kafka_schema = 'personhog/types/v1/person.proto:Person')",
            ),
        ]
    )
    def test_named_collection_engine_carries_the_schema(self, _name: str, schema: str | None, tail: str) -> None:
        serialization = "ProtobufSingle" if schema else "JSONEachRow"
        engine = kafka_engine(topic="t", group="g", serialization=serialization, schema=schema)
        assert engine.endswith(tail), engine

    def test_broker_list_engine_rejects_a_schema(self) -> None:
        with self.assertRaises(ValueError):
            kafka_engine(topic="t", kafka_host="kafka:9092", use_named_collection=False, schema="x.proto:X")
