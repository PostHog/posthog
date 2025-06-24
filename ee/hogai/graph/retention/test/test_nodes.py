from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from ee.hogai.graph.retention.nodes import RetentionGeneratorNode, RetentionPlannerNode, RetentionSchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.models import Action
from posthog.schema import (
    AssistantRetentionActionsNode,
    AssistantRetentionEventsNode,
    AssistantRetentionFilter,
    AssistantRetentionQuery,
    HumanMessage,
    VisualizationMessage,
)
from posthog.test.base import BaseTest


class TestRetentionPlannerNode(BaseTest):
    def test_retention_planner_prompt_has_tools(self):
        node = RetentionPlannerNode(self.team, self.user)
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
        self.action = Action.objects.create(team=self.team, name="Test Action")
        self.schema = AssistantRetentionQuery(
            retentionFilter=AssistantRetentionFilter(
                targetEntity=AssistantRetentionEventsNode(name="targetEntity"),
                returningEntity=AssistantRetentionActionsNode(name=self.action.name, id=self.action.id),
            )
        )

    def test_node_runs(self):
        node = RetentionGeneratorNode(self.team, self.user)
        with patch.object(RetentionGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: RetentionSchemaGeneratorOutput(query=self.schema).model_dump()
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
