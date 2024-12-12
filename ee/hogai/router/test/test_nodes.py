from typing import Any
from unittest.mock import patch

from django.test import override_settings
from langchain_core.messages import AIMessage as LangchainAIMessage, HumanMessage as LangchainHumanMessage
from langchain_core.runnables import RunnableLambda

from ee.hogai.router.nodes import RouterNode, RouterOutput
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    HumanMessage,
    RouterMessage,
    VisualizationMessage,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


@override_settings(IN_UNIT_TESTING=True)
class TestRouterNode(ClickhouseTestMixin, APIBaseTest):
    def test_router(self):
        node = RouterNode(self.team)
        state: Any = AssistantState(messages=[RouterMessage(content="trends")])
        self.assertEqual(node.router(state), "trends")

    def test_node_runs(self):
        with patch(
            "ee.hogai.router.nodes.RouterNode._model",
            return_value=RunnableLambda(lambda _: RouterOutput(visualization_type="funnel")),
        ):
            node = RouterNode(self.team)
            state: Any = AssistantState(messages=[HumanMessage(content="generate trends")])
            next_state = node.run(state, {})
            self.assertEqual(
                next_state,
                PartialAssistantState(messages=[RouterMessage(content="funnel", id=next_state.messages[0].id)]),
            )

        with patch(
            "ee.hogai.router.nodes.RouterNode._model",
            return_value=RunnableLambda(lambda _: RouterOutput(visualization_type="trends")),
        ):
            node = RouterNode(self.team)
            state: Any = AssistantState(messages=[HumanMessage(content="generate trends")])
            next_state = node.run(state, {})
            self.assertEqual(
                next_state,
                PartialAssistantState(messages=[RouterMessage(content="trends", id=next_state.messages[0].id)]),
            )

    def test_node_reconstructs_conversation(self):
        node = RouterNode(self.team)
        state: Any = AssistantState(messages=[HumanMessage(content="generate trends")])
        self.assertEqual(node._construct_messages(state), [LangchainHumanMessage(content="Question: generate trends")])
        state = AssistantState(
            messages=[
                HumanMessage(content="generate trends"),
                RouterMessage(content="trends"),
                VisualizationMessage(),
            ]
        )
        self.assertEqual(
            node._construct_messages(state),
            [LangchainHumanMessage(content="Question: generate trends"), LangchainAIMessage(content="trends")],
        )
