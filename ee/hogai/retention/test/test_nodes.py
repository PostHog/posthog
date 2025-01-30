from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from ee.hogai.retention.nodes import RetentionGeneratorNode, RetentionPlannerNode, RetentionSchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantRetentionFilter,
    AssistantRetentionQuery,
    HumanMessage,
    VisualizationMessage,
)
from posthog.test.base import BaseTest


class TestRetentionPlannerNode(BaseTest):
    def test_retention_planner_prompt_has_tools(self):
        node = RetentionPlannerNode(self.team)
        with patch.object(RetentionPlannerNode, "_model") as model_mock:

            def assert_prompt(prompt):
                self.assertIn("retrieve_event_properties", str(prompt))
                return AIMessage(content="Thought.\nAction: abc")

            model_mock.return_value = RunnableLambda(assert_prompt)
            node.run(AssistantState(messages=[HumanMessage(content="Text")]), {})


class TestRetentionGeneratorNode(BaseTest):
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
