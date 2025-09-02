from posthog.test.base import BaseTest

from ee.hogai.graph.taxonomy.tools import base_final_answer, get_dynamic_entity_tools


class TestDynamicEntityTools(BaseTest):
    def test_get_dynamic_entity_tools_basic(self):
        team_group_types = ["organization", "project"]

        properties_tool, values_tool = get_dynamic_entity_tools(team_group_types)

        self.assertTrue(hasattr(properties_tool, "__annotations__"))
        self.assertTrue(hasattr(values_tool, "__annotations__"))

        # Test that we can create instances with the dynamic types
        properties_instance = properties_tool(entity="organization")
        self.assertEqual(properties_instance.entity, "organization")

        values_instance = values_tool(entity="project", property_name="test_prop")
        self.assertEqual(values_instance.entity, "project")
        self.assertEqual(values_instance.property_name, "test_prop")

    def test_get_dynamic_entity_tools_empty_groups(self):
        team_group_types = []

        properties_tool, values_tool = get_dynamic_entity_tools(team_group_types)

        # Should still work with just person and session
        properties_instance = properties_tool(entity="person")
        self.assertEqual(properties_instance.entity, "person")

        values_instance = values_tool(entity="session", property_name="$session_duration")
        self.assertEqual(values_instance.entity, "session")

    def test_get_dynamic_entity_tools_with_multiple_groups(self):
        team_group_types = ["organization", "project", "account", "team"]

        properties_tool, values_tool = get_dynamic_entity_tools(team_group_types)

        # Test each group type
        for group_type in team_group_types:
            properties_instance = properties_tool(entity=group_type)
            self.assertEqual(properties_instance.entity, group_type)

            values_instance = values_tool(entity=group_type, property_name="test_prop")
            self.assertEqual(values_instance.entity, group_type)

    def test_dynamic_tools_have_docstrings(self):
        team_group_types = ["organization"]

        properties_tool, values_tool = get_dynamic_entity_tools(team_group_types)

        self.assertIn("retrieve property names for a property group", properties_tool.__doc__)
        self.assertIn("retrieve property values for a property name", values_tool.__doc__)

    def test_dynamic_tools_field_descriptions(self):
        team_group_types = ["organization"]

        properties_tool, values_tool = get_dynamic_entity_tools(team_group_types)

        properties_fields = properties_tool.__annotations__
        values_fields = values_tool.__annotations__

        self.assertIn("entity", properties_fields)
        self.assertIn("entity", values_fields)
        self.assertIn("property_name", values_fields)


class TestFinalAnswerModel(BaseTest):
    class final_answer(base_final_answer[str]):
        __doc__ = base_final_answer.__doc__

    def test_final_answer_model_basic(self):
        self.assertEqual(self.final_answer(answer="test").answer, "test")

    def test_final_answer_model_docstring(self):
        self.assertIn("Use this tool to finalize the answer.", self.final_answer.__doc__)
        self.assertIn("ask_user_for_help", self.final_answer.__doc__)

    def test_final_answer_model_field_description(self):
        self.assertIsInstance(self.final_answer(answer="test").answer, str)

    def test_final_answer_model_name(self):
        self.assertEqual(self.final_answer.__name__, "final_answer")
