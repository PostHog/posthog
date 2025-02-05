from unittest.mock import patch

from langchain_core.messages import AIMessage as LangchainAIMessage, HumanMessage as LangchainHumanMessage
from langchain_core.runnables import RunnableLambda
from parameterized import parameterized

from ee.hogai.root.nodes import RootNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantMessage, HumanMessage, RouterMessage
from posthog.test.base import BaseTest, ClickhouseTestMixin


class TestRootNode(ClickhouseTestMixin, BaseTest):
    def test_router(self):
        node = RootNode(self.team)
        state = AssistantState(messages=[RouterMessage(content="trends")])
        self.assertEqual(node.router(state), "trends")

    def test_node_handles_plain_chat_response(self):
        with patch(
            "ee.hogai.root.nodes.RootNode._model",
            return_value=RunnableLambda(
                lambda _: LangchainAIMessage(content="Why did the chicken cross the road? To get to the other side!")
            ),
        ):
            node = RootNode(self.team)
            state_1 = AssistantState(messages=[HumanMessage(content="Tell me a joke")])
            next_state = node.run(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            self.assertIsInstance(next_state.messages[0], AssistantMessage)
            self.assertEqual(
                next_state.messages[0].content, "Why did the chicken cross the road? To get to the other side!"
            )

    @parameterized.expand(
        [
            ["trends"],
            ["funnel"],
            ["retention"],
        ]
    )
    def test_node_handles_insight_tool_call(self, insight_type):
        with patch(
            "ee.hogai.root.nodes.RootNode._model",
            return_value=RunnableLambda(
                lambda _: LangchainAIMessage(
                    content="Hang tight while I check this.",
                    tool_calls=[
                        {
                            "id": "xyz",
                            "name": "retrieve_data_for_question",
                            "args": {"query_description": "Foobar", "query_kind": insight_type},
                        }
                    ],
                )
            ),
        ):
            node = RootNode(self.team)
            state_1 = AssistantState(messages=[HumanMessage(content=f"generate {insight_type}")])
            next_state = node.run(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 2)
            assistant_message = next_state.messages[0]
            self.assertIsInstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, "Hang tight while I check this.")
            self.assertIsNotNone(assistant_message.id)
            router_msg = next_state.messages[1]
            self.assertIsInstance(router_msg, RouterMessage)
            self.assertEqual(router_msg.content, insight_type)
            self.assertIsNotNone(router_msg.id)

    @parameterized.expand(
        [
            ["trends"],
            ["funnel"],
            ["retention"],
        ]
    )
    def test_node_handles_insight_tool_call_without_message(self, insight_type):
        with patch(
            "ee.hogai.root.nodes.RootNode._model",
            return_value=RunnableLambda(
                lambda _: LangchainAIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "xyz",
                            "name": "retrieve_data_for_question",
                            "args": {"query_description": "Foobar", "query_kind": insight_type},
                        }
                    ],
                )
            ),
        ):
            node = RootNode(self.team)
            state_1 = AssistantState(messages=[HumanMessage(content=f"generate {insight_type}")])
            next_state = node.run(state_1, {})
            self.assertIsInstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            router_msg = next_state.messages[0]
            self.assertIsInstance(router_msg, RouterMessage)
            self.assertEqual(router_msg.content, insight_type)
            self.assertIsNotNone(router_msg.id)

    def test_node_reconstructs_conversation(self):
        node = RootNode(self.team)
        state_1 = AssistantState(messages=[HumanMessage(content="Hello")])
        self.assertEqual(node._construct_messages(state_1), [LangchainHumanMessage(content="Hello")])

        # We want full access to message history in root
        state_2 = AssistantState(
            messages=[
                HumanMessage(content="Hello"),
                AssistantMessage(content="Welcome!"),
                HumanMessage(content="Generate trends"),
                RouterMessage(content="trends"),
            ]
        )
        self.assertEqual(
            node._construct_messages(state_2),
            [
                LangchainHumanMessage(content="Hello"),
                LangchainAIMessage(content="Welcome!"),
                LangchainHumanMessage(content="Generate trends"),
                LangchainAIMessage(content="Generating a trends query…"),
            ],
        )
