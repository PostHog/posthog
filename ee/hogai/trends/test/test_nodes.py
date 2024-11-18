from unittest.mock import patch

from django.test import override_settings
from langchain_core.runnables import RunnableLambda

from ee.hogai.trends.nodes import TrendsGeneratorNode, TrendsSchemaGeneratorOutput
from posthog.schema import (
    AssistantTrendsQuery,
    HumanMessage,
    VisualizationMessage,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


@override_settings(IN_UNIT_TESTING=True)
class TestTrendsGeneratorNode(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def setUp(self):
        self.schema = AssistantTrendsQuery(series=[])

    def test_node_runs(self):
        node = TrendsGeneratorNode(self.team)
        with patch.object(TrendsGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: TrendsSchemaGeneratorOutput(reasoning_steps=["step"], answer=self.schema).model_dump()
            )
            new_state = node.run(
                {
                    "messages": [HumanMessage(content="Text")],
                    "plan": "Plan",
                },
                {},
            )
            self.assertEqual(
                new_state,
                {
                    "messages": [
                        VisualizationMessage(answer=self.schema, plan="Plan", reasoning_steps=["step"], done=True)
                    ],
                    "intermediate_steps": None,
                },
            )
