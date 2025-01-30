from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from ee.hogai.trends.nodes import TrendsGeneratorNode, TrendsPlannerNode, TrendsSchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantTrendsQuery,
    HumanMessage,
    VisualizationMessage,
)
from posthog.test.base import BaseTest


class TestTrendsPlannerNode(BaseTest):
    def test_trends_planner_prompt_has_tools(self):
        node = TrendsPlannerNode(self.team)
        with patch.object(TrendsPlannerNode, "_model") as model_mock:

            def assert_prompt(prompt):
                self.assertIn("retrieve_event_properties", str(prompt))
                return AIMessage(content="Thought.\nAction: abc")

            model_mock.return_value = RunnableLambda(assert_prompt)
            node.run(AssistantState(messages=[HumanMessage(content="Text")]), {})


class TestTrendsGeneratorNode(BaseTest):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.schema = AssistantTrendsQuery(series=[])

    def test_node_runs(self):
        node = TrendsGeneratorNode(self.team)
        with patch.object(TrendsGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: TrendsSchemaGeneratorOutput(query=self.schema).model_dump()
            )
            new_state = node.run(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    plan="Plan",
                ),
                {},
            )
            self.assertEqual(
                new_state,
                PartialAssistantState(
                    messages=[VisualizationMessage(answer=self.schema, plan="Plan", id=new_state.messages[0].id)],
                    intermediate_steps=[],
                    plan="",
                ),
            )
