from typing import Any
from unittest.mock import patch

from django.test import override_settings
from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.messages import HumanMessage as LangchainHumanMessage
from langchain_core.runnables import RunnableLambda

from ee.hogai.router.nodes import RouterNode, RouterOutput
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
        state: Any = {"messages": [RouterMessage(content="trends")]}
        self.assertEqual(node.router(state), "trends")

    def test_node_runs(self):
        with patch(
            "ee.hogai.router.nodes.RouterNode._model",
            return_value=RunnableLambda(lambda _: RouterOutput(visualization_type="funnel")),
        ):
            node = RouterNode(self.team)
            state: Any = {"messages": [HumanMessage(content="generate trends")]}
            self.assertEqual(node.run(state, {}), {"messages": [RouterMessage(content="funnel")]})

        with patch(
            "ee.hogai.router.nodes.RouterNode._model",
            return_value=RunnableLambda(lambda _: RouterOutput(visualization_type="trends")),
        ):
            node = RouterNode(self.team)
            state: Any = {"messages": [HumanMessage(content="generate trends")]}
            self.assertEqual(node.run(state, {}), {"messages": [RouterMessage(content="trends")]})

    def test_node_reconstructs_conversation(self):
        node = RouterNode(self.team)
        state: Any = {"messages": [HumanMessage(content="generate trends")]}
        self.assertEqual(
            node._reconstruct_conversation(state), [LangchainHumanMessage(content="Question: generate trends")]
        )
        state = {
            "messages": [
                HumanMessage(content="generate trends"),
                RouterMessage(content="trends"),
                VisualizationMessage(),
            ]
        }
        self.assertEqual(
            node._reconstruct_conversation(state),
            [LangchainHumanMessage(content="Question: generate trends"), LangchainAIMessage(content="trends")],
        )
