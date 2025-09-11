from datetime import datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import Mock, patch

from langchain_core.agents import AgentAction
from parameterized import parameterized
from pydantic import BaseModel

from posthog.schema import (
    ActorsPropertyTaxonomyResponse,
    CachedActorsPropertyTaxonomyQueryResponse,
    CachedEventTaxonomyQueryResponse,
    EventTaxonomyItem,
)

from posthog.models import Action
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit, TaxonomyToolNotFoundError


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
            create_group_type_mapping_without_created_at(
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
        create_group_type_mapping_without_created_at(
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

    def test_format_properties_formats(self):
        props = [("prop1", "String", "Test description"), ("prop2", "Numeric", None)]

        # Test XML format
        xml_result = self.toolkit._format_properties_xml(props)
        self.assertIn("<properties>", xml_result)
        self.assertIn("<String>", xml_result)
        self.assertIn("<Numeric>", xml_result)
        self.assertIn("<name>prop1</name>", xml_result)
        self.assertIn("<description>Test description</description>", xml_result)
        self.assertIn("<name>prop2</name>", xml_result)

        # Test YAML format
        yaml_result = self.toolkit._format_properties_yaml(props)
        self.assertIn("properties:", yaml_result)
        self.assertIn("String:", yaml_result)
        self.assertIn("Numeric:", yaml_result)
        self.assertIn("name: prop1", yaml_result)
        self.assertIn("description: Test description", yaml_result)

    @parameterized.expand(
        [
            ("retrieve_entity_properties", {"entity": "person"}, "retrieve_entity_properties", {"entity": "person"}),
            (
                "retrieve_event_properties",
                {"event_name": "test_event"},
                "retrieve_event_properties",
                {"event_name": "test_event"},
            ),
            (
                "ask_user_for_help",
                {"request": "Can you help me?"},
                "ask_user_for_help",
                {"request": "Can you help me?"},
            ),
            (
                "retrieve_entity_property_values",
                {"entity": "person", "property_name": "email"},
                "retrieve_entity_property_values",
                {"entity": "person", "property_name": "email"},
            ),
            (
                "retrieve_event_property_values",
                {"event_name": "test_event", "property_name": "$browser"},
                "retrieve_event_property_values",
                {"event_name": "test_event", "property_name": "$browser"},
            ),
            ("retrieve_entity_properties", {"entity": "session"}, "retrieve_entity_properties", {"entity": "session"}),
        ]
    )
    def test_get_tool_input_model_with_valid_tools(self, tool_name, tool_input, expected_name, expected_args):
        """Test get_tool_input_model with various valid tools."""
        action = AgentAction(tool=tool_name, tool_input=tool_input, log="test log")

        result = self.toolkit.get_tool_input_model(action)

        self.assertEqual(result.name, expected_name)
        self.assertIsInstance(result.arguments, BaseModel)

        # Check that all expected arguments are present and correct
        for key, value in expected_args.items():
            self.assertEqual(getattr(result.arguments, key), value)

    def test_get_tool_input_model_with_custom_tools(self):
        """Test get_tool_input_model when custom tools are available."""

        # Create a custom toolkit with custom tools
        class CustomToolkit(TaxonomyAgentToolkit):
            def _get_custom_tools(self):
                class CustomTool(BaseModel):
                    custom_field: str

                return [CustomTool]

        custom_toolkit = CustomToolkit(self.team)

        action = AgentAction(tool="custom_tool", tool_input={"custom_field": "test_value"}, log="test log")

        result = custom_toolkit.get_tool_input_model(action)

        self.assertEqual(result.name, "custom_tool")
        self.assertEqual(result.arguments.custom_field, "test_value")
        self.assertIsInstance(result.arguments, BaseModel)

    def test_get_tools_handles_not_implemented_error(self):
        """Test that get_tools properly handles NotImplementedError from _get_custom_tools."""

        # Create a toolkit that doesn't override _get_custom_tools
        class BasicToolkit(TaxonomyAgentToolkit):
            def _get_custom_tools(self):
                raise NotImplementedError("This is a test error")

        basic_toolkit = BasicToolkit(self.team)

        # Should not raise NotImplementedError, should fall back to default tools
        tools = basic_toolkit.get_tools()

        # Verify we get the default tools (should contain the standard taxonomy tools)
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 0)

        tool_names = [tool.__name__ for tool in tools]
        expected_tools = [
            "retrieve_event_properties",
            "retrieve_entity_properties",
            "retrieve_entity_property_values",
            "retrieve_event_property_values",
            "ask_user_for_help",
        ]

        for expected_tool in expected_tools:
            self.assertIn(expected_tool, tool_names)

    def test_get_tools_with_custom_tools(self):
        """Test that get_tools properly combines default and custom tools."""

        class CustomToolkit(TaxonomyAgentToolkit):
            def _get_custom_tools(self):
                # Return some mock custom tools
                def custom_tool_1():
                    pass

                def custom_tool_2():
                    pass

                return [custom_tool_1, custom_tool_2]

        custom_toolkit = CustomToolkit(self.team)

        # Should return both default and custom tools
        tools = custom_toolkit.get_tools()

        # Verify we get both default and custom tools
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 0)

        # Get tool names
        tool_names = [tool.__name__ for tool in tools]

        expected_default_tools = [
            "retrieve_event_properties",
            "retrieve_entity_properties",
            "retrieve_entity_property_values",
            "retrieve_event_property_values",
            "ask_user_for_help",
        ]

        for expected_tool in expected_default_tools:
            self.assertIn(expected_tool, tool_names)

        # Verify custom tools are present
        expected_custom_tools = ["custom_tool_1", "custom_tool_2"]

        for expected_tool in expected_custom_tools:
            self.assertIn(expected_tool, tool_names)

        self.assertEqual(len(tools), len(expected_default_tools) + len(expected_custom_tools))
