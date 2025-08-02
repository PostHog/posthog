from pydantic import BaseModel, Field

from ee.hogai.graph.taxonomy.tools import (
    get_dynamic_entity_tools,
    create_final_answer_model,
)
from posthog.test.base import BaseTest


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


class TestCreateFinalAnswerModel(BaseTest):
    def test_create_final_answer_model_basic(self):
        class TestResponseModel(BaseModel):
            result: str
            count: int = 0

        final_answer_model = create_final_answer_model(TestResponseModel)

        # Test that we can create an instance
        test_data = TestResponseModel(result="test", count=5)
        final_answer = final_answer_model(data=test_data)

        self.assertEqual(final_answer.data.result, "test")
        self.assertEqual(final_answer.data.count, 5)

    def test_create_final_answer_model_docstring(self):
        class TestResponseModel(BaseModel):
            result: str

        final_answer_model = create_final_answer_model(TestResponseModel)

        self.assertIn("Use this tool to finalize the answer.", final_answer_model.__doc__)
        self.assertIn("ask_user_for_help", final_answer_model.__doc__)

    def test_create_final_answer_model_field_description(self):
        class TestResponseModel(BaseModel):
            result: str

        final_answer_model = create_final_answer_model(TestResponseModel)

        # Create an instance to verify the field works properly
        test_data = TestResponseModel(result="test")
        final_answer = final_answer_model(data=test_data)

        self.assertIsInstance(final_answer.data, TestResponseModel)

    def test_create_final_answer_model_complex_response(self):
        class ComplexResponseModel(BaseModel):
            filters: list[dict] = Field(default_factory=list)
            metadata: dict = Field(default_factory=dict)
            success: bool = True

        final_answer_model = create_final_answer_model(ComplexResponseModel)

        test_data = ComplexResponseModel(
            filters=[{"property": "email", "value": "test@example.com"}], metadata={"source": "taxonomy"}, success=True
        )
        final_answer = final_answer_model(data=test_data)

        self.assertEqual(len(final_answer.data.filters), 1)
        self.assertEqual(final_answer.data.filters[0]["property"], "email")
        self.assertEqual(final_answer.data.metadata["source"], "taxonomy")
        self.assertTrue(final_answer.data.success)

    def test_final_answer_model_name(self):
        class TestResponseModel(BaseModel):
            result: str

        final_answer_model = create_final_answer_model(TestResponseModel)

        # The class should be named 'final_answer'
        self.assertEqual(final_answer_model.__name__, "final_answer")
