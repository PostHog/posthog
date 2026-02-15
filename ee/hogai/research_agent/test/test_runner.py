from uuid import uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, patch

from posthog.schema import AgentMode, AssistantMessage, HumanMessage

from ee.hogai.research_agent.runner import STREAMING_NODES, VERBOSE_NODES, ResearchAgentRunner
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.models import Conversation


class TestResearchAgentRunnerConfiguration(BaseTest):
    def test_streaming_nodes_includes_root(self):
        self.assertIn(AssistantNodeName.ROOT, STREAMING_NODES)

    def test_verbose_nodes_includes_root(self):
        self.assertIn(AssistantNodeName.ROOT, VERBOSE_NODES)

    def test_verbose_nodes_includes_root_tools(self):
        self.assertIn(AssistantNodeName.ROOT_TOOLS, VERBOSE_NODES)

    def test_verbose_nodes_includes_generators(self):
        self.assertIn(AssistantNodeName.TRENDS_GENERATOR, VERBOSE_NODES)
        self.assertIn(AssistantNodeName.FUNNEL_GENERATOR, VERBOSE_NODES)
        self.assertIn(AssistantNodeName.RETENTION_GENERATOR, VERBOSE_NODES)
        self.assertIn(AssistantNodeName.SQL_GENERATOR, VERBOSE_NODES)

    def test_verbose_nodes_includes_insights_search(self):
        self.assertIn(AssistantNodeName.INSIGHTS_SEARCH, VERBOSE_NODES)

    def test_verbose_nodes_includes_query_executor(self):
        self.assertIn(AssistantNodeName.QUERY_EXECUTOR, VERBOSE_NODES)

    def test_streaming_nodes_is_subset_of_verbose_nodes(self):
        self.assertTrue(STREAMING_NODES.issubset(VERBOSE_NODES))


class TestResearchAgentRunner(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    def _create_runner(self, new_message=None, is_new_conversation=False):
        return ResearchAgentRunner(
            team=self.team,
            conversation=self.conversation,
            new_message=new_message,
            user=self.user,
            is_new_conversation=is_new_conversation,
        )

    def test_get_initial_state_sets_supermode_to_plan(self):
        message = HumanMessage(content="Research this topic", id=str(uuid4()))
        runner = self._create_runner(new_message=message, is_new_conversation=True)

        initial_state = runner.get_initial_state()

        self.assertIsInstance(initial_state, AssistantState)
        self.assertEqual(initial_state.supermode, AgentMode.PLAN)

    def test_get_initial_state_sets_start_id(self):
        message = HumanMessage(content="Research this topic", id=str(uuid4()))
        runner = self._create_runner(new_message=message, is_new_conversation=True)

        initial_state = runner.get_initial_state()

        # The runner creates a copy of the message with a new ID,
        # and the start_id is set to the new message ID
        self.assertIsNotNone(initial_state.start_id)
        self.assertEqual(initial_state.start_id, initial_state.messages[0].id)

    def test_get_initial_state_includes_message(self):
        message = HumanMessage(content="Research this topic", id=str(uuid4()))
        runner = self._create_runner(new_message=message, is_new_conversation=True)

        initial_state = runner.get_initial_state()

        self.assertEqual(len(initial_state.messages), 1)
        self.assertEqual(initial_state.messages[0].content, "Research this topic")

    def test_get_initial_state_with_no_message(self):
        runner = self._create_runner(new_message=None, is_new_conversation=True)

        initial_state = runner.get_initial_state()

        self.assertIsInstance(initial_state, AssistantState)
        self.assertEqual(len(initial_state.messages), 0)

    def test_get_resumed_state_returns_partial_state(self):
        message = HumanMessage(content="Continue research", id=str(uuid4()))
        runner = self._create_runner(new_message=message, is_new_conversation=False)

        resumed_state = runner.get_resumed_state()

        self.assertIsInstance(resumed_state, PartialAssistantState)

    def test_get_resumed_state_sets_graph_status_to_resumed(self):
        message = HumanMessage(content="Continue research", id=str(uuid4()))
        runner = self._create_runner(new_message=message, is_new_conversation=False)

        resumed_state = runner.get_resumed_state()

        self.assertEqual(resumed_state.graph_status, "resumed")

    def test_get_resumed_state_includes_message(self):
        message = HumanMessage(content="Continue research", id=str(uuid4()))
        runner = self._create_runner(new_message=message, is_new_conversation=False)

        resumed_state = runner.get_resumed_state()

        self.assertEqual(len(resumed_state.messages), 1)
        self.assertEqual(resumed_state.messages[0].content, "Continue research")

    def test_get_resumed_state_with_no_message(self):
        runner = self._create_runner(new_message=None, is_new_conversation=False)

        resumed_state = runner.get_resumed_state()

        self.assertIsInstance(resumed_state, PartialAssistantState)
        self.assertEqual(len(resumed_state.messages), 0)

    def test_state_type_is_assistant_state(self):
        runner = self._create_runner()

        self.assertEqual(runner._state_type, AssistantState)

    def test_partial_state_type_is_partial_assistant_state(self):
        runner = self._create_runner()

        self.assertEqual(runner._partial_state_type, PartialAssistantState)

    def test_use_checkpointer_is_true(self):
        runner = self._create_runner()

        self.assertTrue(runner._use_checkpointer)


class TestResearchAgentRunnerAstream(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    def _create_runner(self, new_message=None, is_new_conversation=False):
        return ResearchAgentRunner(
            team=self.team,
            conversation=self.conversation,
            new_message=new_message,
            user=self.user,
            is_new_conversation=is_new_conversation,
        )

    async def test_astream_calls_report_conversation_state_with_deep_research(self):
        """Test that astream reports conversation state with 'deep research' label."""

        message = HumanMessage(content="Research this topic", id=str(uuid4()))
        runner = self._create_runner(new_message=message, is_new_conversation=True)

        # Mock the parent astream to yield a single event
        async def mock_parent_astream(*args, **kwargs):
            yield ("run_id", AssistantMessage(content="Research response", id="msg-1"))

        mock_report = AsyncMock()

        with (
            patch.object(runner.__class__.__bases__[0], "astream", mock_parent_astream),
            patch.object(runner, "_report_conversation_state", mock_report),
        ):
            # Consume the stream
            events = []
            async for event in runner.astream():
                events.append(event)

            # Verify _report_conversation_state was called with "deep research"
            mock_report.assert_called_once()
            call_args = mock_report.call_args
            self.assertEqual(call_args[0][0], "deep research")
