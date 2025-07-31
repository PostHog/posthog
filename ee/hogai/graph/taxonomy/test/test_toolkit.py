from unittest.mock import Mock, patch
from parameterized import parameterized
from datetime import datetime

from langchain_core.agents import AgentAction
from pydantic import BaseModel

from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit, TaxonomyToolNotFoundError
from posthog.models import Action
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.schema import (
    CachedEventTaxonomyQueryResponse,
    EventTaxonomyItem,
    CachedActorsPropertyTaxonomyQueryResponse,
    ActorsPropertyTaxonomyResponse,
)
from posthog.test.base import BaseTest, ClickhouseTestMixin


class DummyToolkit(TaxonomyAgentToolkit):
    def get_tools(self):
        return self._get_default_tools()


class TestTaxonomyAgentToolkit(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.toolkit = DummyToolkit(self.team)
        self.action = Action.objects.create(team=self.team, name="test_action", steps_json=[{"event": "test_event"}])

    def test_toolkit_initialization(self):
        self.assertEqual(self.toolkit._team, self.team)
        self.assertIsInstance(self.toolkit._team_group_types, list)
        self.assertIsInstance(self.toolkit._entity_names, list)

    @parameterized.expand(
        [
            ("person", ["person", "session"]),
            ("session", ["person", "session"]),
        ]
    )
    def test_entity_names_basic(self, entity, expected_base):
        self.assertIn(entity, self.toolkit._entity_names)
        for expected in expected_base:
            self.assertIn(expected, self.toolkit._entity_names)

    def test_entity_names_with_groups(self):
        # Create group type mappings
        for i, group_type in enumerate(["organization", "project"]):
            GroupTypeMapping.objects.create(
                team=self.team, project_id=self.team.project_id, group_type_index=i, group_type=group_type
            )

        toolkit = DummyToolkit(self.team)
        expected = ["person", "session", "organization", "project"]
        self.assertEqual(toolkit._entity_names, expected)

    @parameterized.expand(
        [
            ("$session_duration", True, "30, 146, 2"),
            ("$channel_type", True, "Direct"),
            ("nonexistent_property", False, "does not exist"),
        ]
    )
    def test_retrieve_session_properties(self, property_name, should_contain_values, expected_content):
        result = self.toolkit._retrieve_session_properties(property_name)
        if should_contain_values:
            self.assertIn(expected_content, result)
        else:
            self.assertIn(expected_content, result)

    def test_enrich_props_with_descriptions(self):
        props = [("$browser", "String"), ("custom_prop", "Numeric")]
        enriched = self.toolkit._enrich_props_with_descriptions("event", props)

        browser_prop = next((p for p in enriched if p[0] == "$browser"), None)
        self.assertIsNotNone(browser_prop)
        self.assertEqual(browser_prop[1], "String")
        self.assertIsNotNone(browser_prop[2])

    @parameterized.expand(
        [
            ([], 0, False, "The property does not have any values"),
            (["value1", "value2"], None, False, "value1, value2 and many more"),
            (["value1", "value2"], 5, False, "value1, value2 and 3 more"),
            (["string_val"], 1, True, '"string_val"'),
            ([1.0, 2.0], 2, False, "1, 2"),
        ]
    )
    def test_format_property_values(self, sample_values, sample_count, format_as_string, expected_substring):
        result = self.toolkit._format_property_values(sample_values, sample_count, format_as_string)
        self.assertIn(expected_substring, result)

    def _create_property_definition(self, prop_type, name="test_prop", group_type_index=None):
        """Helper to create property definitions"""
        kwargs = {"team": self.team, "name": name, "property_type": PropertyType.String}
        if prop_type == PropertyDefinition.Type.GROUP:
            kwargs["type"] = PropertyDefinition.Type.GROUP
            kwargs["group_type_index"] = group_type_index
        else:
            kwargs["type"] = prop_type

        return PropertyDefinition.objects.create(**kwargs)

    def _create_mock_taxonomy_response(self, response_type="event", **kwargs):
        """Helper to create mock taxonomy responses"""
        if response_type == "event":
            return CachedEventTaxonomyQueryResponse(
                cache_key="test",
                is_cached=False,
                last_refresh=datetime.now().isoformat(),
                next_allowed_client_refresh=datetime.now().isoformat(),
                timezone="UTC",
                results=[EventTaxonomyItem(**kwargs)],
            )
        elif response_type == "actors":
            return CachedActorsPropertyTaxonomyQueryResponse(
                cache_key="test",
                is_cached=False,
                last_refresh=datetime.now().isoformat(),
                next_allowed_client_refresh=datetime.now().isoformat(),
                timezone="UTC",
                results=ActorsPropertyTaxonomyResponse(**kwargs),
            )

    def test_retrieve_entity_properties_person(self):
        self._create_property_definition(PropertyDefinition.Type.PERSON, "email")
        result = self.toolkit.retrieve_entity_properties("person")
        self.assertIn("email", result)
        self.assertIn("String", result)

    def test_retrieve_entity_properties_session(self):
        result = self.toolkit.retrieve_entity_properties("session")
        self.assertIn("$session_duration", result)
        self.assertIn("properties", result)

    def test_retrieve_entity_properties_group(self):
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type_index=0, group_type="organization"
        )
        self._create_property_definition(PropertyDefinition.Type.GROUP, "org_name", group_type_index=0)
        result = self.toolkit.retrieve_entity_properties("organization")
        self.assertIn("org_name", result)

    @parameterized.expand(
        [
            ("invalid_entity", "Entity invalid_entity not found"),
            ("person", "Properties do not exist in the taxonomy for the entity person."),
        ]
    )
    def test_retrieve_entity_properties_edge_cases(self, entity, expected_content):
        result = self.toolkit.retrieve_entity_properties(entity)
        self.assertIn(expected_content, result)

    @patch("ee.hogai.graph.taxonomy.toolkit.ActorsPropertyTaxonomyQueryRunner")
    def test_retrieve_entity_property_values_person(self, mock_runner_class):
        self._create_property_definition(PropertyDefinition.Type.PERSON, "email")

        mock_response = self._create_mock_taxonomy_response(
            response_type="actors", sample_values=["test@example.com", "user@test.com"], sample_count=2
        )

        mock_runner = Mock()
        mock_runner.run.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        result = self.toolkit.retrieve_entity_property_values("person", "email")
        self.assertIn("test@example.com", result)

    def test_retrieve_entity_property_values_invalid_entity(self):
        result = self.toolkit.retrieve_entity_property_values("invalid", "prop")
        self.assertIn("Entity invalid not found", result)

    @patch("ee.hogai.graph.taxonomy.toolkit.EventTaxonomyQueryRunner")
    def test_retrieve_event_or_action_properties(self, mock_runner_class):
        self._create_property_definition(PropertyDefinition.Type.EVENT, "$browser")

        mock_response = self._create_mock_taxonomy_response(property="$browser", sample_values=[], sample_count=0)

        mock_runner = Mock()
        mock_runner.run.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        result = self.toolkit.retrieve_event_or_action_properties("test_event")
        self.assertIn("$browser", result)

    def test_retrieve_event_or_action_properties_action_not_found(self):
        Action.objects.all().delete()
        result = self.toolkit.retrieve_event_or_action_properties(999)
        self.assertEqual(result, "No actions exist in the project.")

    @patch("ee.hogai.graph.taxonomy.toolkit.EventTaxonomyQueryRunner")
    def test_retrieve_event_or_action_property_values(self, mock_runner_class):
        self._create_property_definition(PropertyDefinition.Type.EVENT, "$browser")

        mock_response = self._create_mock_taxonomy_response(
            property="$browser", sample_values=["Chrome", "Firefox"], sample_count=2
        )

        mock_runner = Mock()
        mock_runner.run.return_value = mock_response
        mock_runner_class.return_value = mock_runner

        result = self.toolkit.retrieve_event_or_action_property_values("test_event", "$browser")
        self.assertIn("Chrome", result)
        self.assertIn("Firefox", result)

    def test_handle_incorrect_response(self):
        class TestModel(BaseModel):
            field: str = "test"

        response = TestModel()
        result = self.toolkit.handle_incorrect_response(response)
        self.assertIn("test", result)

    @parameterized.expand(
        [
            ("retrieve_entity_properties", {"entity": "person"}, "mocked"),
            ("retrieve_entity_property_values", {"entity": "person", "property_name": "email"}, "mocked"),
            ("retrieve_event_properties", {"event_name": "test_event"}, "mocked"),
            ("retrieve_event_property_values", {"event_name": "test_event", "property_name": "$browser"}, "mocked"),
            ("ask_user_for_help", {"request": "Help needed"}, "Help needed"),
            ("final_answer", {}, "Taxonomy finalized"),
        ]
    )
    @patch.object(DummyToolkit, "retrieve_entity_properties", return_value="mocked")
    @patch.object(DummyToolkit, "retrieve_entity_property_values", return_value="mocked")
    @patch.object(DummyToolkit, "retrieve_event_or_action_properties", return_value="mocked")
    @patch.object(DummyToolkit, "retrieve_event_or_action_property_values", return_value="mocked")
    def test_handle_tools(self, tool_name, tool_args, expected_result, *mocks):
        class Arguments(BaseModel):
            pass

        for key, value in tool_args.items():
            setattr(Arguments, key, value)

        class ToolInput(BaseModel):
            name: str
            arguments: Arguments

        tool_input = ToolInput(name=tool_name, arguments=Arguments(**tool_args))
        tool_name_result, result = self.toolkit.handle_tools(tool_name, tool_input)

        self.assertEqual(result, expected_result)
        self.assertEqual(tool_name_result, tool_name)

    def test_handle_tools_invalid_tool(self):
        class ToolInput(BaseModel):
            name: str = "invalid_tool"
            arguments: dict = {}

        tool_input = ToolInput()

        with self.assertRaises(TaxonomyToolNotFoundError):
            self.toolkit.handle_tools("invalid_tool", tool_input)

    def test_get_tool_input_model(self):
        action = AgentAction(tool="test_tool", tool_input={"test": "value"}, log="test_log")

        with patch.object(self.toolkit, "_create_dynamic_tool") as mock_create:

            class MockTool(BaseModel):
                name: str
                arguments: dict

                @classmethod
                def model_validate(cls, data):
                    return cls(**data)

            mock_create.return_value = MockTool
            result = self.toolkit.get_tool_input_model(action)
            self.assertIsInstance(result, MockTool)

    def test_generate_properties_output_formats(self):
        props = [("prop1", "String", "Test description"), ("prop2", "Numeric", None)]

        # Test XML format
        xml_result = self.toolkit._generate_properties_xml(props)
        self.assertIn("<properties>", xml_result)
        self.assertIn("<String>", xml_result)
        self.assertIn("<Numeric>", xml_result)
        self.assertIn("<name>prop1</name>", xml_result)
        self.assertIn("<description>Test description</description>", xml_result)
        self.assertIn("<name>prop2</name>", xml_result)

        # Test YAML format
        yaml_result = self.toolkit._generate_properties_yaml(props)
        self.assertIn("properties:", yaml_result)
        self.assertIn("String:", yaml_result)
        self.assertIn("Numeric:", yaml_result)
        self.assertIn("name: prop1", yaml_result)
        self.assertIn("description: Test description", yaml_result)
