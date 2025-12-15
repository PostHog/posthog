from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.api.event_definition_generators.base import EventDefinitionGenerator


class TestGenerator(EventDefinitionGenerator):
    """Minimal test generator for testing base class functionality"""

    def __init__(self, version: str = "1.0.0"):
        self._version = version

    def generator_version(self) -> str:
        return self._version

    def language_name(self) -> str:
        return "Test"

    def generate(self, event_definitions, schema_map) -> str:
        return ""  # Not needed for hash tests


class TestEventDefinitionGeneratorBase(BaseTest):
    @parameterized.expand(
        [
            (
                "Hashes should be deterministic for the same input",
                "1.0.0",
                [("1", "event_a", [("field1", "String", True)])],
                [("1", "event_a", [("field1", "String", True)])],
                True,
            ),
            (
                "If a type changes, the hashes should differ",
                "1.0.0",
                [("1", "event_a", [("field1", "String", True)])],
                [("1", "event_a", [("field1", "Numeric", True)])],
                False,
            ),
            (
                "If the required flag changes, the hashes should defer",
                "1.0.0",
                [("1", "event_a", [("field1", "String", True)])],
                [("1", "event_a", [("field1", "String", False)])],
                False,
            ),
            (
                "If the name changes, the hashes should differ",
                "1.0.0",
                [("1", "event_a", [("field1", "String", True)])],
                [("1", "event_a", [("field2", "String", True)])],
                False,
            ),
            (
                "If the generator version changes, the hashes should differ",
                "1.0.0",
                [("1", "event_a", [("field1", "String", True)])],
                [("1", "event_a", [("field1", "String", True)])],
                False,
                "2.0.0",
            ),
            (
                "Hashes should be deterministic regardless of the order of properties",
                "1.0.0",
                [("1", "event_a", [("zzz_field", "String", True), ("aaa_field", "Numeric", False)])],
                [("1", "event_a", [("aaa_field", "Numeric", False), ("zzz_field", "String", True)])],
                True,
            ),
            (
                "Hashes should be deterministic regardless of the order of events",
                "1.0.0",
                [("1", "zzz_event", [("field", "String", True)]), ("2", "aaa_event", [("field", "String", True)])],
                [("2", "aaa_event", [("field", "String", True)]), ("1", "zzz_event", [("field", "String", True)])],
                True,
            ),
            (
                "New properties should generate a new hash",
                "1.0.0",
                [("1", "event_a", [("field1", "String", True)])],
                [("1", "event_a", [("field1", "String", True), ("field2", "Numeric", False)])],
                False,
            ),
            (
                "Removed propeties should generate a new hash",
                "1.0.0",
                [("1", "event_a", [("field1", "String", True), ("field2", "Numeric", False)])],
                [("1", "event_a", [("field1", "String", True)])],
                False,
            ),
            (
                "New events should generate a new hash",
                "1.0.0",
                [("1", "event_a", [("field1", "String", True)])],
                [("1", "event_a", [("field1", "String", True)]), ("2", "event_b", [("field2", "Numeric", False)])],
                False,
            ),
            (
                "Removed events should generate a new hash",
                "1.0.0",
                [("1", "event_a", [("field1", "String", True)]), ("2", "event_b", [("field2", "Numeric", False)])],
                [("1", "event_a", [("field1", "String", True)])],
                False,
            ),
        ]
    )
    def test_calculate_schema_hash(
        self,
        name: str,
        version1: str,
        schema1_spec: list[tuple[str, str, list[tuple[str, str, bool]]]],
        schema2_spec: list[tuple[str, str, list[tuple[str, str, bool]]]],
        should_be_equal: bool,
        version2: str | None = None,
    ) -> None:
        version2 = version2 or version1

        events1, schema_map1 = self._build_schema(schema1_spec)
        hash1 = TestGenerator(version1).calculate_schema_hash(events1, schema_map1)  # type: ignore[arg-type]

        events2, schema_map2 = self._build_schema(schema2_spec)
        hash2 = TestGenerator(version2).calculate_schema_hash(events2, schema_map2)  # type: ignore[arg-type]

        self.assertEqual(
            hash1 == hash2,
            should_be_equal,
            f"{name} failed: Expected hashes to be {'equal' if should_be_equal else 'different'}\n"
            f"Hash 1: {hash1}\n"
            f"Hash 2: {hash2}\n"
            f"Schema 1: {schema1_spec}\n"
            f"Schema 2: {schema2_spec}",
        )

    def _build_schema(
        self, schema_spec: list[tuple[str, str, list[tuple[str, str, bool]]]]
    ) -> tuple[list[MagicMock], dict[str, list[MagicMock]]]:
        """
        Build mock events and schema_map from specification.

        Args:
            schema_spec: List of tuples (event_id, event_name, properties)
                        where properties is a list of tuples (prop_name, prop_type, is_required)

        Returns:
            Tuple of (events list, schema_map dict)
        """
        events: list[MagicMock] = []
        schema_map: dict[str, list[MagicMock]] = {}

        for event_id, event_name, prop_specs in schema_spec:
            event = MagicMock()
            event.id = event_id
            event.name = event_name
            events.append(event)

            properties: list[MagicMock] = []
            for prop_name, prop_type, is_required in prop_specs:
                prop = MagicMock()
                prop.name = prop_name
                prop.property_type = prop_type
                prop.is_required = is_required
                properties.append(prop)

            schema_map[event_id] = properties

        return events, schema_map
