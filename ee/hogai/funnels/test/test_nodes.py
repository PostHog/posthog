from unittest.mock import patch

from django.test import override_settings
from langchain_core.runnables import RunnableLambda

from ee.hogai.funnels.nodes import FunnelGeneratorNode, FunnelsSchemaGeneratorOutput
from posthog.schema import (
    AssistantFunnelsQuery,
    HumanMessage,
    VisualizationMessage,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


@override_settings(IN_UNIT_TESTING=True)
class TestFunnelsGeneratorNode(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        self.schema = AssistantFunnelsQuery(series=[])

    def test_node_runs(self):
        node = FunnelGeneratorNode(self.team)
        with patch.object(FunnelGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: FunnelsSchemaGeneratorOutput(query=self.schema).model_dump()
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
                    "messages": [VisualizationMessage(answer=self.schema, plan="Plan", done=True)],
                    "intermediate_steps": None,
                },
            )
