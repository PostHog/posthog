from posthog.test.base import BaseTest

from pydantic import BaseModel

from ee.hogai.chat_agent.taxonomy.tools import base_final_answer, get_dynamic_entity_tools


class TestDynamicEntityTools(BaseTest):
    def test_get_dynamic_entity_tools_basic(self):
        team_group_types: list[str] = ["organization", "project"]

        properties_tool, values_tool = get_dynamic_entity_tools(team_group_types)

        assert hasattr(properties_tool, "__annotations__")
        assert hasattr(values_tool, "__annotations__")

        # Test that we can create instances with the dynamic types
        properties_instance = properties_tool(entity="organization")
        assert properties_instance.entity == "organization"

        values_instance = values_tool(entity="project", property_name="test_prop")
        assert values_instance.entity == "project"
        assert values_instance.property_name == "test_prop"

    def test_get_dynamic_entity_tools_empty_groups(self):
        team_group_types: list[str] = []

        properties_tool, values_tool = get_dynamic_entity_tools(team_group_types)

        # Should still work with just person and session
        properties_instance = properties_tool(entity="person")
        assert properties_instance.entity == "person"

        values_instance = values_tool(entity="session", property_name="$session_duration")
        assert values_instance.entity == "session"

    def test_get_dynamic_entity_tools_with_multiple_groups(self):
        team_group_types = ["organization", "project", "account", "team"]

        properties_tool, values_tool = get_dynamic_entity_tools(team_group_types)

        # Test each group type
        for group_type in team_group_types:
            properties_instance = properties_tool(entity=group_type)
            assert properties_instance.entity == group_type

            values_instance = values_tool(entity=group_type, property_name="test_prop")
            assert values_instance.entity == group_type

    def test_dynamic_tools_have_docstrings(self):
        team_group_types = ["organization"]

        properties_tool, values_tool = get_dynamic_entity_tools(team_group_types)

        assert "retrieve property names for a property group" in properties_tool.__doc__
        assert "retrieve property values for a property name" in values_tool.__doc__

    def test_dynamic_tools_field_descriptions(self):
        team_group_types = ["organization"]

        properties_tool, values_tool = get_dynamic_entity_tools(team_group_types)

        properties_fields = properties_tool.__annotations__
        values_fields = values_tool.__annotations__

        assert "entity" in properties_fields
        assert "entity" in values_fields
        assert "property_name" in values_fields


class TestFinalAnswerModel(BaseTest):
    class TestAnswerModel(BaseModel):
        value: str

    class final_answer(base_final_answer[TestAnswerModel]):
        __doc__ = base_final_answer.__doc__

    def test_final_answer_model_basic(self):
        test_answer = self.TestAnswerModel(value="test")
        assert self.final_answer(answer=test_answer).answer.value == "test"

    def test_final_answer_model_docstring(self):
        doc = self.final_answer.__doc__
        assert doc is not None
        assert "Use this tool to finalize the answer." in doc
        assert "ask_user_for_help" in doc

    def test_final_answer_model_field_description(self):
        test_answer = self.TestAnswerModel(value="test")
        assert isinstance(self.final_answer(answer=test_answer).answer, self.TestAnswerModel)

    def test_final_answer_model_name(self):
        assert self.final_answer.__name__ == "final_answer"
