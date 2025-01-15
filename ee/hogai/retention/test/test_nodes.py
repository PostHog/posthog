from unittest.mock import patch

from django.test import override_settings
from langchain_core.runnables import RunnableLambda

from ee.hogai.retention.nodes import RetentionGeneratorNode, RetentionSchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantRetentionQuery,
    HumanMessage,
    AssistantRetentionFilter,
    VisualizationMessage,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


@override_settings(IN_UNIT_TESTING=True)
class TestRetentionGeneratorNode(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.schema = AssistantRetentionQuery(
            retentionFilter=AssistantRetentionFilter(
                targetEntity={"id": "targetEntity", "type": "events", "name": "targetEntity"},
                returningEntity={"id": "returningEntity", "type": "events", "name": "returningEntity"},
            )
        )

    def test_node_runs(self):
        node = RetentionGeneratorNode(self.team)
        with patch.object(RetentionGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: RetentionSchemaGeneratorOutput(query=self.schema).model_dump()
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
