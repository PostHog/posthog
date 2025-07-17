from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from ee.hogai.graph.trends.nodes import TrendsGeneratorNode, TrendsSchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantTrendsQuery,
    HumanMessage,
    VisualizationMessage,
)
from posthog.test.base import BaseTest


class TestTrendsGeneratorNode(BaseTest):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.schema = AssistantTrendsQuery(series=[])

    def test_node_runs(self):
        node = TrendsGeneratorNode(self.team, self.user)
        with patch.object(TrendsGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: TrendsSchemaGeneratorOutput(query=self.schema).model_dump()
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
