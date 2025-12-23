from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.messages import AIMessage as LangchainAIMessage
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import AgentMode, AssistantMessage, AssistantToolCall, HumanMessage

from ee.hogai.chat_agent.mode_manager import ChatAgentModeManager
from ee.hogai.context import AssistantContextManager
from ee.hogai.utils.tests import FakeChatOpenAI
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AssistantNodeName, NodePath, PartialAssistantState

from ..product_analytics import ProductAnalyticsAgentToolkit


class TestProductAnalyticsAgentToolkit(BaseTest):
    @patch("posthoganalytics.feature_enabled")
    async def test_create_insight_tool_when_agent_modes_enabled(self, mock_feature_enabled):
        """Test that create_insight tool is included when agent modes feature flag is enabled"""
        mock_feature_enabled.return_value = True

        toolkit = ProductAnalyticsAgentToolkit(
            team=self.team,
            user=self.user,
            context_manager=AssistantContextManager(self.team, self.user, RunnableConfig(configurable={})),
        )

        # Check that CreateInsightTool is in the tools property
        tool_classes = toolkit.tools
        tool_class_names = [tool_class.__name__ for tool_class in tool_classes]
        self.assertIn("CreateInsightTool", tool_class_names)


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
            "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model",
            return_value=FakeChatOpenAI(
                responses=[
                    LangchainAIMessage(
                        content=content,
                        tool_calls=[
                            {
                                "id": "xyz",
                                "name": "create_insight",
                                "args": {"query_description": "Foobar", "query_kind": insight_type},
                            }
                        ],
                    )
                ],
            ),
        ):
            context_manager = AssistantContextManager(
                team=self.team, user=self.user, config=RunnableConfig(configurable={})
            )
            mode_manager = ChatAgentModeManager(
                team=self.team,
                user=self.user,
                node_path=(
                    NodePath(name=AssistantNodeName.ROOT, message_id="test_id", tool_call_id="test_tool_call_id"),
                ),
                context_manager=context_manager,
                mode=AgentMode.PRODUCT_ANALYTICS,
            )
            node = mode_manager.node

            state_1 = AssistantState(messages=[HumanMessage(content=f"generate {insight_type}")])
            next_state = await node.arun(state_1, {})
            assert isinstance(next_state, PartialAssistantState)
            # The state includes context messages + original message + generated message
            self.assertGreaterEqual(len(next_state.messages), 1)
            assistant_message = next_state.messages[-1]
            self.assertIsInstance(assistant_message, AssistantMessage)
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
                    name="create_insight",
                    args={"query_description": "Foobar", "query_kind": insight_type},
                ),
            )
