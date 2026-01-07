from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig

from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes.toolkit import AgentToolkit, AgentToolkitManager
from ee.hogai.tools.todo_write import TodoWriteExample, TodoWriteTool
from ee.hogai.utils.types import AssistantState


class TestAgentToolkitManager(BaseTest):
    async def test_accumulates_todo_examples_from_both_toolkits(self):
        agent_positive = TodoWriteExample(example="agent positive", reasoning="agent reasoning")
        agent_negative = TodoWriteExample(example="agent negative", reasoning="agent reasoning")
        mode_positive = TodoWriteExample(example="mode positive", reasoning="mode reasoning")
        mode_negative = TodoWriteExample(example="mode negative", reasoning="mode reasoning")

        class AgentToolkitWithExamples(AgentToolkit):
            POSITIVE_TODO_EXAMPLES = [agent_positive]
            NEGATIVE_TODO_EXAMPLES = [agent_negative]

            @property
            def tools(self):
                return [TodoWriteTool]

        class ModeToolkitWithExamples(AgentToolkit):
            POSITIVE_TODO_EXAMPLES = [mode_positive]
            NEGATIVE_TODO_EXAMPLES = [mode_negative]

            @property
            def tools(self):
                return []

        AgentToolkitManager.configure(
            agent_toolkit=AgentToolkitWithExamples,
            mode_toolkit=ModeToolkitWithExamples,
            mode_registry={},
        )

        context_manager = AssistantContextManager(
            team=self.team, user=self.user, config=RunnableConfig(configurable={})
        )
        manager = AgentToolkitManager(team=self.team, user=self.user, context_manager=context_manager)

        with patch.object(TodoWriteTool, "create_tool_class", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = MagicMock()

            state = AssistantState(messages=[])
            await manager.get_tools(state, RunnableConfig(configurable={}))

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs

            assert call_kwargs["positive_examples"] == [agent_positive, mode_positive]
            assert call_kwargs["negative_examples"] == [agent_negative, mode_negative]
