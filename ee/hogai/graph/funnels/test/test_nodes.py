from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from ee.hogai.graph.funnels.nodes import FunnelGeneratorNode, FunnelPlannerNode, FunnelsSchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantFunnelsFilter,
    AssistantFunnelsQuery,
    HumanMessage,
    VisualizationMessage,
)
from posthog.test.base import BaseTest


class TestFunnelPlannerNode(BaseTest):
    def test_funnels_planner_prompt_has_tools(self):
        node = FunnelPlannerNode(self.team, self.user)
        with patch.object(FunnelPlannerNode, "_model") as model_mock:

            def assert_prompt(prompt):
                self.assertIn("retrieve_event_properties", str(prompt))
                return AIMessage(content="Thought.\nAction: abc")

            model_mock.return_value = RunnableLambda(assert_prompt)
            node.run(AssistantState(messages=[HumanMessage(content="Text")]), {})


class TestFunnelsGeneratorNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.schema = AssistantFunnelsQuery(series=[])

    def test_node_runs(self):
        node = FunnelGeneratorNode(self.team, self.user)
        with patch.object(FunnelGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: FunnelsSchemaGeneratorOutput(query=self.schema).model_dump()
            )
            new_state = node.run(
                AssistantState(messages=[HumanMessage(content="Text")], plan="Plan", root_tool_insight_plan="question"),
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

    def test_schema_does_not_require_aggregation_by_hogql(self):
        """Catches the regression where the schema set funnelAggregateByHogQL."""
        schema = AssistantFunnelsQuery(series=[], funnelsFilter=AssistantFunnelsFilter())
        self.assertIsNone(schema.funnelsFilter.funnelAggregateByHogQL)
