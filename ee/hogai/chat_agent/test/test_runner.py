from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.schema import AgentMode, HumanMessage

from ee.hogai.chat_agent.runner import ChatAgentRunner
from ee.models.assistant import Conversation


class TestChatAgentRunner(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    def _create_runner(self, **kwargs) -> ChatAgentRunner:
        with patch("ee.hogai.chat_agent.runner.AssistantGraph.compile_full_graph", return_value=MagicMock()):
            return ChatAgentRunner(team=self.team, conversation=self.conversation, user=self.user, **kwargs)

    def test_selected_agent_mode_when_missing(self):
        runner = self._create_runner()
        assert runner._selected_agent_mode is None
        runner = self._create_runner(agent_mode=AgentMode.SQL)
        assert runner._selected_agent_mode == AgentMode.SQL

    def test_get_initial_state_without_agent_mode(self):
        """Test that agent_mode is not set in initial state when not explicitly provided."""
        runner = self._create_runner(new_message=HumanMessage(content="test"))
        state = runner.get_initial_state()

        assert state.agent_mode is None

    def test_get_initial_state_with_agent_mode(self):
        """Test that agent_mode is set in initial state when explicitly provided."""
        runner = self._create_runner(new_message=HumanMessage(content="test"), agent_mode=AgentMode.SQL)
        state = runner.get_initial_state()

        assert state.agent_mode == AgentMode.SQL

    def test_get_initial_state_without_message(self):
        """Test that initial state is created without agent_mode when no message is provided."""
        runner = self._create_runner()
        state = runner.get_initial_state()

        assert state.messages == []
        assert state.agent_mode is None

    def test_get_resumed_state_without_agent_mode(self):
        """Test that agent_mode is not set in resumed state when not explicitly provided."""
        runner = self._create_runner(new_message=HumanMessage(content="test"))
        state = runner.get_resumed_state()

        assert state.agent_mode is None

    def test_get_resumed_state_with_agent_mode(self):
        """Test that agent_mode is set in resumed state when explicitly provided."""
        runner = self._create_runner(new_message=HumanMessage(content="test"), agent_mode=AgentMode.SQL)
        state = runner.get_resumed_state()

        assert state.agent_mode == AgentMode.SQL

    def test_get_resumed_state_without_message(self):
        """Test that resumed state is created without agent_mode when no message is provided."""
        runner = self._create_runner()
        state = runner.get_resumed_state()

        assert state.messages == []
        assert state.agent_mode is None
