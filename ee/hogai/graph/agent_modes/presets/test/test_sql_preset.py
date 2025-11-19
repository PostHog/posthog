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

from ..sql import SQLAgentToolkit, sql_agent


class TestSQLAgentToolkit(BaseTest):
    @patch("ee.hogai.graph.agent_modes.nodes.AgentExecutable._get_model")
    async def test_get_tools_includes_execute_sql_tool(self, mock_model):
        """Test that execute_sql tool is included in toolkit tools"""
        mock_model.return_value = FakeChatOpenAI(responses=[LangchainAIMessage(content="Response")])

        node = SQLAgentToolkit(
            team=self.team,
            user=self.user,
            context_manager=AssistantContextManager(self.team, self.user, RunnableConfig(configurable={})),
        )
        state = AssistantState(messages=[HumanMessage(content="Test")])

        tools = await node.get_tools(state, {})
        tool_names = [tool.get_name() for tool in tools]
        self.assertIn("execute_sql", tool_names)


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
            "ee.hogai.graph.agent_modes.nodes.AgentExecutable._get_model",
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
            node = sql_agent.node_class(
                team=self.team,
                user=self.user,
                toolkit_class=sql_agent.toolkit_class,
                node_path=(
                    NodePath(name=AssistantNodeName.ROOT, message_id="test_id", tool_call_id="test_tool_call_id"),
                ),
            )
            state_1 = AssistantState(messages=[HumanMessage(content="execute sql query")])
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
                    name="execute_sql",
                    args={"query": query},
                ),
            )
