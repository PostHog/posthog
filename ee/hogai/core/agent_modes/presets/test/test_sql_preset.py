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

from ..sql import SQLAgentToolkit


class TestSQLAgentToolkit(BaseTest):
    async def test_get_tools_includes_execute_sql_tool(self):
        """Test that execute_sql tool is included in toolkit tools"""
        toolkit = SQLAgentToolkit(
            team=self.team,
            user=self.user,
            context_manager=AssistantContextManager(self.team, self.user, RunnableConfig(configurable={})),
        )

        # Check that execute_sql is in the tools property
        tool_classes = toolkit.tools
        tool_class_names = [tool_class.__name__ for tool_class in tool_classes]
        self.assertIn("ExecuteSQLTool", tool_class_names)


class TestSQLAgentNode(BaseTest):
    @parameterized.expand(
        [
            ["SELECT * FROM events", "Let me execute this SQL query."],
            ["SELECT count() FROM events WHERE timestamp > now() - INTERVAL 7 DAY", "Analyzing the data."],
            ["SELECT * FROM events", ""],
        ]
    )
    async def test_node_handles_execute_sql_tool_call(self, query, content):
        with patch(
            "ee.hogai.core.agent_modes.executables.AgentExecutable._get_model",
            return_value=FakeChatOpenAI(
                responses=[
                    LangchainAIMessage(
                        content=content,
                        tool_calls=[
                            {
                                "id": "xyz",
                                "name": "execute_sql",
                                "args": {"query": query},
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
                mode=AgentMode.SQL,
            )
            node = mode_manager.node

            state_1 = AssistantState(messages=[HumanMessage(content="execute sql query")])
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
                    name="execute_sql",
                    args={"query": query},
                ),
            )
