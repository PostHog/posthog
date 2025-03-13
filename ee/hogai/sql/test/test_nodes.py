from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from ee.hogai.sql.nodes import SQLGeneratorNode, SQLPlannerNode, SQLSchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantHogQLQuery,
    HumanMessage,
    VisualizationMessage,
)
from posthog.test.base import BaseTest


class TestSQLPlannerNode(BaseTest):
    def test_sql_planner_prompt_has_tools(self):
        node = SQLPlannerNode(self.team)
        with patch.object(SQLPlannerNode, "_model") as model_mock:

            def assert_prompt(prompt):
                self.assertIn("retrieve_event_properties", str(prompt))
                return AIMessage(content="Thought.\nAction: abc")

            model_mock.return_value = RunnableLambda(assert_prompt)
            node.run(AssistantState(messages=[HumanMessage(content="Text")]), {})


class TestSQLGeneratorNode(BaseTest):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.schema = AssistantHogQLQuery(query="SELECT 1")

    def test_node_runs(self):
        node = SQLGeneratorNode(self.team)
        with patch.object(SQLGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: SQLSchemaGeneratorOutput(query=self.schema).model_dump()
            )
            new_state = node.run(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    plan="Plan",
                    root_tool_insight_plan="question",
                ),
                {},
            )
            self.assertEqual(
                new_state,
                PartialAssistantState(
                    messages=[
                        VisualizationMessage(
                            query="question", answer=self.schema, plan="Plan", id=new_state.messages[0].id
                        )
                    ],
                    intermediate_steps=[],
                    plan="",
                ),
            )
