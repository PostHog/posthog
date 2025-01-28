from unittest.mock import patch

from django.test import override_settings
from langchain_core.runnables import RunnableLambda

from ee.hogai.funnels.nodes import FunnelGeneratorNode, FunnelsSchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantFunnelsQuery,
    HumanMessage,
    VisualizationMessage,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


@override_settings(IN_UNIT_TESTING=True)
class TestFunnelsGeneratorNode(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.schema = AssistantFunnelsQuery(series=[])

    def test_node_runs(self):
        node = FunnelGeneratorNode(self.team)
        with patch.object(FunnelGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: FunnelsSchemaGeneratorOutput(query=self.schema).model_dump()
            )
            new_state = node.run(
                AssistantState(messages=[HumanMessage(content="Text")], plan="Plan"),
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
