from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import AssistantMessage, AssistantToolCall, HumanMessage

from ee.hogai.context import AssistantContextManager
from ee.hogai.utils.tests import FakeChatOpenAI
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AssistantNodeName, NodePath, PartialAssistantState

from ..product_analytics import ProductAnalyticsAgentToolkit, product_analytics_agent


class TestProductAnalyticsAgentToolkit(BaseTest):
    @patch("ee.hogai.graph.agent_modes.nodes.AgentNode._get_model")
    @patch("posthoganalytics.feature_enabled")
    async def test_get_tools_session_summarization_feature_flag(self, mock_feature_enabled, mock_model):
        """Test that session_summarization tool is only included when feature flag is enabled"""
        mock_model.return_value = FakeChatOpenAI(responses=[LangchainAIMessage(content="Response")])

        node = ProductAnalyticsAgentToolkit(
            team=self.team,
            user=self.user,
            context_manager=AssistantContextManager(self.team, self.user, RunnableConfig(configurable={})),
        )
        state = AssistantState(messages=[HumanMessage(content="Test")])

        # Test with feature flag enabled
        mock_feature_enabled.return_value = True
        tools_with_flag = await node.get_tools(state, {})
        tool_names_with_flag = [tool.get_name() for tool in tools_with_flag]
        self.assertIn("session_summarization", tool_names_with_flag)

        # Test with feature flag disabled
        mock_feature_enabled.return_value = False
        tools_without_flag = await node.get_tools(state, {})
        tool_names_without_flag = [tool.get_name() for tool in tools_without_flag]
        self.assertNotIn("session_summarization", tool_names_without_flag)


class TestProductAnalyticsAgentNode(BaseTest):
    @parameterized.expand(
        [
            ["trends", "Hang tight while I check this."],
            ["funnel", "Hang tight while I check this."],
            ["retention", "Hang tight while I check this."],
            ["trends", ""],
            ["funnel", ""],
            ["retention", ""],
        ]
    )
    async def test_node_handles_insight_tool_call(self, insight_type, content):
        with patch(
            "ee.hogai.graph.agent_modes.nodes.AgentNode._get_model",
            return_value=FakeChatOpenAI(
                responses=[
                    LangchainAIMessage(
                        content=content,
                        tool_calls=[
                            {
                                "id": "xyz",
                                "name": "create_and_query_insight",
                                "args": {"query_description": "Foobar", "query_kind": insight_type},
                            }
                        ],
                    )
                ],
            ),
        ):
            node = product_analytics_agent.node_class(
                team=self.team,
                user=self.user,
                toolkit_class=product_analytics_agent.toolkit_class,
                node_path=(
                    NodePath(name=AssistantNodeName.ROOT, message_id="test_id", tool_call_id="test_tool_call_id"),
                ),
            )
            state_1 = AssistantState(messages=[HumanMessage(content=f"generate {insight_type}")])
            next_state = await node(state_1, {})
            assert isinstance(next_state, PartialAssistantState)
            self.assertEqual(len(next_state.messages), 1)
            self.assertIsInstance(next_state.messages[0], AssistantMessage)
            assistant_message = next_state.messages[0]
            assert isinstance(assistant_message, AssistantMessage)
            self.assertEqual(assistant_message.content, content)
            self.assertIsNotNone(assistant_message.id)
            self.assertIsNotNone(assistant_message.tool_calls)
            assert assistant_message.tool_calls is not None
            self.assertEqual(len(assistant_message.tool_calls), 1)
            self.assertEqual(
                assistant_message.tool_calls[0],
                AssistantToolCall(
                    id="xyz",
                    name="create_and_query_insight",
                    args={"query_description": "Foobar", "query_kind": insight_type},
                ),
            )
