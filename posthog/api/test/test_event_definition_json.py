from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import orjson
from rest_framework import status

from posthog.api.event_definition_generators.json import JsonGenerator
from posthog.models import EventDefinition, EventSchema, SchemaPropertyGroup, SchemaPropertyGroupProperty


class TestJsonGenerator(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.generator = JsonGenerator()

    def test_generator_metadata(self):
        self.assertEqual(self.generator.language_name(), "JSON")
        self.assertEqual(self.generator.generator_version(), "0.0.1")

    def test_generate_simple_event(self):
        event = MagicMock()
        event.id = "1"
        event.name = "simple_event"
        event.description = "A simple test event"

        # Mock properties
        prop1 = self._create_mock_property("user_id", "String", required=True)
        prop2 = self._create_mock_property("is_active", "Boolean", required=False)

        schema_map = {"1": [prop1, prop2]}

        json_output = self.generator.generate([event], schema_map)  # type: ignore
        data = orjson.loads(json_output)

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "simple_event")
        self.assertEqual(data[0]["description"], "A simple test event")

        properties = data[0]["properties"]
        self.assertEqual(len(properties), 2)

        # Check properties (sorted by name)
        self.assertEqual(properties[0]["name"], "is_active")
        self.assertEqual(properties[0]["type"], "Boolean")
        self.assertEqual(properties[0]["required"], False)

        self.assertEqual(properties[1]["name"], "user_id")
        self.assertEqual(properties[1]["type"], "String")
        self.assertEqual(properties[1]["required"], True)

    def test_generate_empty(self):
        json_output = self.generator.generate([], {})  # type: ignore
        data = orjson.loads(json_output)
        self.assertEqual(data, [])

    def _create_mock_property(self, name: str, property_type: str, required: bool = False) -> MagicMock:
        prop = MagicMock()
        prop.name = name
        prop.property_type = property_type
        prop.is_required = required
        return prop


class TestJsonGeneratorAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Create test data
        self.event_def_1 = EventDefinition.objects.create(team=self.team, project=self.project, name="file_downloaded")
        self.prop_group_1 = SchemaPropertyGroup.objects.create(
            team=self.team, project=self.project, name="File Properties"
        )
        SchemaPropertyGroupProperty.objects.create(
            property_group=self.prop_group_1,
            name="file_name",
            property_type="String",
            is_required=True,
        )
        EventSchema.objects.create(event_definition=self.event_def_1, property_group=self.prop_group_1)

    @patch("posthog.api.event_definition_generators.base.report_user_action")
    def test_json_endpoint_success(self, mock_report):
        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertIn("content", data)
        self.assertIn("event_count", data)
        self.assertIn("schema_hash", data)
        self.assertEqual(data["generator_version"], "0.0.1")

        # Verify content is valid JSON and contains our event
        content = orjson.loads(data["content"])
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["name"], "file_downloaded")
        self.assertEqual(content[0]["properties"][0]["name"], "file_name")

        self._test_telemetry_called(mock_report)

    def test_json_endpoint_excludes_system_events(self):
        EventDefinition.objects.create(team=self.team, project=self.project, name="$autocapture")
        EventDefinition.objects.create(team=self.team, project=self.project, name="$pageview")

        response = self.client.get(f"/api/projects/{self.project.id}/event_definitions/json")
        content = orjson.loads(response.json()["content"])

        event_names = [e["name"] for e in content]
        self.assertNotIn("$autocapture", event_names)
        self.assertIn("$pageview", event_names)

    def test_json_schema_hash_is_deterministic(self):
        response1 = self.client.get(f"/api/projects/{self.project.id}/event_definitions/json")
        hash1 = response1.json()["schema_hash"]

        response2 = self.client.get(f"/api/projects/{self.project.id}/event_definitions/json")
        hash2 = response2.json()["schema_hash"]

        self.assertEqual(hash1, hash2, "Schema hash should be deterministic")

    def _test_telemetry_called(self, mock_report) -> None:
        self.assertEqual(mock_report.call_count, 1)
        call_args = mock_report.call_args
        self.assertEqual(call_args[0][0], self.user)
        self.assertEqual(call_args[0][1], "event definitions generated")
        telemetry_props = call_args[0][2]
        self.assertEqual(telemetry_props["language"], "JSON")
        self.assertEqual(telemetry_props["team_id"], self.team.id)
