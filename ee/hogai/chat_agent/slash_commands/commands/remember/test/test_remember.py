import pytest
from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.slash_commands.commands.remember import RememberCommand
from ee.hogai.utils.types import AssistantState
from ee.models.assistant import CoreMemory


class TestRememberCommand(BaseTest):
    def setUp(self):
        super().setUp()
        self.command = RememberCommand(self.team, self.user)

    def test_get_memory_content_with_args(self):
        """Test extracting memory content from /remember command."""
        state = AssistantState(messages=[HumanMessage(content="/remember My main KPI is MAU")])
        result = self.command.get_memory_content(state)
        assert result == "My main KPI is MAU"

    def test_get_memory_content_without_args(self):
        """Test that /remember without args returns empty string."""
        state = AssistantState(messages=[HumanMessage(content="/remember")])
        result = self.command.get_memory_content(state)
        assert result == ""

    def test_get_memory_content_with_whitespace(self):
        """Test that extra whitespace is trimmed."""
        state = AssistantState(messages=[HumanMessage(content="/remember   test fact   ")])
        result = self.command.get_memory_content(state)
        assert result == "test fact"

    def test_get_memory_content_non_remember_message(self):
        """Test that non-remember messages return None."""
        state = AssistantState(messages=[HumanMessage(content="Hello world")])
        result = self.command.get_memory_content(state)
        assert result is None

    def test_get_memory_content_empty_messages(self):
        """Test that empty messages return None."""
        state = AssistantState(messages=[])
        result = self.command.get_memory_content(state)
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_appends_to_memory(self):
        """Test that execute appends content to core memory."""
        state = AssistantState(messages=[HumanMessage(content="/remember Test fact to remember")])
        config = RunnableConfig(configurable={"thread_id": "test-thread"})

        result = await self.command.execute(config, state)

        assert len(result.messages) == 1
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        assert "remember" in message.content.lower()

        core_memory = await sync_to_async(CoreMemory.objects.get)(team=self.team)
        assert "Test fact to remember" in core_memory.text

    @pytest.mark.asyncio
    async def test_execute_without_content_returns_help(self):
        """Test that /remember without content returns help message."""
        state = AssistantState(messages=[HumanMessage(content="/remember")])
        config = RunnableConfig(configurable={"thread_id": "test-thread"})

        result = await self.command.execute(config, state)

        assert len(result.messages) == 1
        message = result.messages[0]
        assert isinstance(message, AssistantMessage)
        assert isinstance(message.content, str)
        assert "Usage:" in message.content

    @pytest.mark.asyncio
    async def test_execute_appends_multiple_memories(self):
        """Test that multiple remember commands append correctly."""
        config = RunnableConfig(configurable={"thread_id": "test-thread"})

        state1 = AssistantState(messages=[HumanMessage(content="/remember First fact")])
        await self.command.execute(config, state1)

        state2 = AssistantState(messages=[HumanMessage(content="/remember Second fact")])
        await self.command.execute(config, state2)

        core_memory = await sync_to_async(CoreMemory.objects.get)(team=self.team)
        assert "First fact" in core_memory.text
        assert "Second fact" in core_memory.text
