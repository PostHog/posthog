from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from ee.hogai.graph.sql.nodes import SQLGeneratorNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantHogQLQuery,
    HumanMessage,
    VisualizationMessage,
)
from posthog.test.base import BaseTest


class TestSQLGeneratorNode(BaseTest):
    maxDiff = None

    def test_node_runs(self):
        node = SQLGeneratorNode(self.team, self.user)
        with patch.object(SQLGeneratorNode, "_model") as generator_model_mock:
            answer = AssistantHogQLQuery(query="SELECT 1")
            generator_model_mock.return_value = RunnableLambda(lambda _: answer.model_dump())
            new_state = node.run(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    plan="Plan",
                    root_tool_insight_plan="question",
                ),
                {},
            )

            assert new_state == PartialAssistantState(
                messages=[
                    VisualizationMessage(
                        query="question",
                        answer=answer,
                        plan="Plan",
                        id=new_state.messages[0].id if new_state.messages else None,
                    )
                ],
                intermediate_steps=[],
                plan="",
            )
