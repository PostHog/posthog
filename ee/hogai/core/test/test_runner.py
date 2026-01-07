from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import anthropic
from parameterized import parameterized

from posthog.schema import AssistantEventType, FailureMessage

from ee.hogai.core.base import BaseAssistantGraph
from ee.hogai.utils.types.base import AssistantState, PartialAssistantState
from ee.models.assistant import Conversation


@asynccontextmanager
async def mock_lock_conversation():
    yield


async def _async_generator_that_raises(exception: Exception) -> AsyncIterator[None]:
    raise exception
    yield  # type: ignore[unreachable]


class TestRunnerLLMProviderErrorHandling(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    def _create_mock_runner(self, exception_to_raise):
        """Create a mock runner with all necessary dependencies."""
        from ee.hogai.core.runner import BaseAgentRunner

        mock_graph = MagicMock()
        mock_graph.astream = MagicMock(return_value=_async_generator_that_raises(exception_to_raise))
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(values={}, next=None))
        mock_graph.aupdate_state = AsyncMock()

        mock_stream_processor = MagicMock()
        mock_stream_processor.mark_id_as_streamed = MagicMock()

        class TestRunner(BaseAgentRunner):
            def get_initial_state(self):
                return AssistantState(messages=[])

            def get_resumed_state(self):
                return PartialAssistantState(messages=[])

        runner = TestRunner(
            team=self.team,
            conversation=self.conversation,
            user=self.user,
            graph_class=cast(type[BaseAssistantGraph], mock_graph),
            state_type=AssistantState,
            partial_state_type=PartialAssistantState,
            stream_processor=mock_stream_processor,
        )
        runner._graph = mock_graph

        return runner, mock_graph

    @parameterized.expand(
        [
            (
                "anthropic_bad_request",
                anthropic.BadRequestError(
                    message="Your credit balance is too low to access the Anthropic API.",
                    response=httpx.Response(
                        status_code=400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
                    ),
                    body={"type": "error", "error": {"type": "invalid_request_error"}},
                ),
                "anthropic",
            ),
            (
                "openai_api_error",
                openai.APIError(
                    message="Rate limit exceeded",
                    request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
                    body=None,
                ),
                "openai",
            ),
        ]
    )
    async def test_llm_api_errors_are_handled_gracefully(self, _name, exception, expected_provider):
        runner, mock_graph = self._create_mock_runner(exception)

        with (
            patch.object(runner, "_init_or_update_state", new_callable=AsyncMock, return_value=None),
            patch.object(runner, "_lock_conversation", return_value=mock_lock_conversation()),
            patch("ee.hogai.core.runner.LLM_PROVIDER_ERROR_COUNTER") as mock_counter,
            patch("ee.hogai.core.runner.posthoganalytics") as mock_posthog,
            patch("ee.hogai.core.runner.logger") as mock_logger,
        ):
            results = []
            async for event_type, message in runner.astream(
                stream_message_chunks=False, stream_first_message=False, stream_only_assistant_messages=True
            ):
                results.append((event_type, message))

            # Verify that a FailureMessage was yielded
            assert len(results) == 1
            event_type, message = results[0]
            assert event_type == AssistantEventType.MESSAGE
            assert isinstance(message, FailureMessage)
            assert (
                message.content
                == "I'm unable to respond right now due to a temporary service issue. Please try again later."
            )

            # Verify state was reset
            mock_graph.aupdate_state.assert_called()

            # Verify Prometheus counter was incremented with correct provider
            mock_counter.labels.assert_called_with(provider=expected_provider)
            mock_counter.labels.return_value.inc.assert_called_once()

            # Verify error was logged
            mock_logger.exception.assert_called_once()
            call_args = mock_logger.exception.call_args
            assert call_args[0][0] == "llm_provider_error"
            assert call_args[1]["provider"] == expected_provider

            # Verify exception was captured
            mock_posthog.capture_exception.assert_called_once()
            capture_call_args = mock_posthog.capture_exception.call_args
            assert capture_call_args[1]["properties"]["error_type"] == "llm_provider_error"
            assert capture_call_args[1]["properties"]["provider"] == expected_provider


class TestRunnerSubagentBehavior(BaseTest):
    """
    Tests for subagent-specific behavior when use_checkpointer=False.

    Subagents differ from the main agent in several ways:
    - They skip interrupt handling
    - They don't reset state on errors
    - They don't lock the conversation
    - They skip checkpoint-related state initialization
    """

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    def _create_runner(self, use_checkpointer: bool, graph_mock=None):
        """Create a runner with specified checkpointer setting."""
        from ee.hogai.core.runner import BaseAgentRunner

        mock_graph = graph_mock or MagicMock()
        if not graph_mock:
            mock_graph.aget_state = AsyncMock(return_value=MagicMock(values={}, next=None))
            mock_graph.aupdate_state = AsyncMock()

        mock_stream_processor = MagicMock()
        mock_stream_processor.mark_id_as_streamed = MagicMock()

        class TestRunner(BaseAgentRunner):
            def get_initial_state(self):
                return AssistantState(messages=[])

            def get_resumed_state(self):
                return PartialAssistantState(messages=[])

        runner = TestRunner(
            team=self.team,
            conversation=self.conversation,
            user=self.user,
            graph_class=cast(type[BaseAssistantGraph], mock_graph),
            state_type=AssistantState,
            partial_state_type=PartialAssistantState,
            stream_processor=mock_stream_processor,
            use_checkpointer=use_checkpointer,
        )
        runner._graph = mock_graph

        return runner, mock_graph

    @parameterized.expand(
        [
            ("with_checkpointer", True, True),
            ("without_checkpointer", False, False),
        ]
    )
    async def test_interrupt_handling_depends_on_checkpointer(self, _name, use_checkpointer, should_check_interrupts):
        """
        When use_checkpointer=False (subagent), the runner should skip interrupt handling
        and return early after streaming.
        """

        async def empty_stream():
            yield
            return

        runner, mock_graph = self._create_runner(use_checkpointer)
        mock_graph.astream = MagicMock(return_value=empty_stream())

        # Set up aget_state to return a state with pending next steps (interrupt)
        mock_state = MagicMock()
        mock_state.values = {}
        mock_state.next = ["some_node"]  # Indicates pending interrupt
        mock_state.tasks = []
        mock_graph.aget_state = AsyncMock(return_value=mock_state)

        with (
            patch.object(runner, "_init_or_update_state", new_callable=AsyncMock, return_value=None),
            patch.object(runner, "_lock_conversation", return_value=mock_lock_conversation()),
        ):
            results = []
            async for event_type, message in runner.astream(
                stream_message_chunks=False, stream_first_message=False, stream_only_assistant_messages=True
            ):
                results.append((event_type, message))

        if should_check_interrupts:
            mock_graph.aget_state.assert_called()
        else:
            mock_graph.aget_state.assert_not_called()

    @parameterized.expand(
        [
            ("with_checkpointer", True, True),
            ("without_checkpointer", False, False),
        ]
    )
    async def test_state_reset_on_llm_error_depends_on_checkpointer(self, _name, use_checkpointer, should_reset_state):
        """
        When use_checkpointer=False (subagent), state should NOT be reset on LLM errors.
        """
        exception = anthropic.BadRequestError(
            message="Error",
            response=httpx.Response(
                status_code=400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            ),
            body={"type": "error", "error": {"type": "invalid_request_error"}},
        )

        runner, mock_graph = self._create_runner(use_checkpointer)
        mock_graph.astream = MagicMock(return_value=_async_generator_that_raises(exception))

        with (
            patch.object(runner, "_init_or_update_state", new_callable=AsyncMock, return_value=None),
            patch.object(runner, "_lock_conversation", return_value=mock_lock_conversation()),
            patch("ee.hogai.core.runner.LLM_PROVIDER_ERROR_COUNTER"),
            patch("ee.hogai.core.runner.posthoganalytics"),
            patch("ee.hogai.core.runner.logger"),
        ):
            results = []
            async for event_type, message in runner.astream(
                stream_message_chunks=False, stream_first_message=False, stream_only_assistant_messages=True
            ):
                results.append((event_type, message))

            # Both should yield a failure message
            assert len(results) == 1
            assert isinstance(results[0][1], FailureMessage)

            # Only checkpointer mode should reset state
            if should_reset_state:
                mock_graph.aupdate_state.assert_called()
            else:
                mock_graph.aupdate_state.assert_not_called()

    @parameterized.expand(
        [
            ("with_checkpointer", True, True),
            ("without_checkpointer", False, False),
        ]
    )
    async def test_state_reset_on_general_exception_depends_on_checkpointer(
        self, _name, use_checkpointer, should_reset_state
    ):
        """
        When use_checkpointer=False (subagent), state should NOT be reset on general exceptions.
        """
        exception = RuntimeError("Unexpected error")

        runner, mock_graph = self._create_runner(use_checkpointer)
        mock_graph.astream = MagicMock(return_value=_async_generator_that_raises(exception))

        # Set up state for checkpointer case
        mock_state = MagicMock()
        mock_state.values = {"messages": []}
        mock_state.next = None
        mock_graph.aget_state = AsyncMock(return_value=mock_state)

        with (
            patch.object(runner, "_init_or_update_state", new_callable=AsyncMock, return_value=None),
            patch.object(runner, "_lock_conversation", return_value=mock_lock_conversation()),
            patch("ee.hogai.core.runner.posthoganalytics"),
            patch("ee.hogai.core.runner.logger"),
        ):
            results = []
            async for event_type, message in runner.astream(
                stream_message_chunks=False, stream_first_message=False, stream_only_assistant_messages=True
            ):
                results.append((event_type, message))

            if should_reset_state:
                mock_graph.aupdate_state.assert_called()
            else:
                mock_graph.aupdate_state.assert_not_called()

    async def test_subagent_lock_conversation_does_not_update_status(self):
        """
        When use_checkpointer=False (subagent), _lock_conversation should yield
        immediately without updating conversation status.
        """
        runner, _ = self._create_runner(use_checkpointer=False)

        # Capture initial status
        initial_status = self.conversation.status

        async with runner._lock_conversation():
            # Status should not have changed during the context
            await self.conversation.arefresh_from_db()
            assert self.conversation.status == initial_status

        # Status should still be unchanged after exiting
        await self.conversation.arefresh_from_db()
        assert self.conversation.status == initial_status

    async def test_main_agent_lock_conversation_updates_status(self):
        """
        When use_checkpointer=True (main agent), _lock_conversation should
        update conversation status to IN_PROGRESS and then to IDLE.
        """
        runner, _ = self._create_runner(use_checkpointer=True)

        # Ensure conversation starts as IDLE
        self.conversation.status = Conversation.Status.IDLE
        await self.conversation.asave()

        async with runner._lock_conversation():
            await self.conversation.arefresh_from_db()
            assert self.conversation.status == Conversation.Status.IN_PROGRESS

        await self.conversation.arefresh_from_db()
        assert self.conversation.status == Conversation.Status.IDLE

    @parameterized.expand(
        [
            ("with_checkpointer", True, True),
            ("without_checkpointer", False, False),
        ]
    )
    async def test_init_or_update_state_checkpoint_lookup_depends_on_checkpointer(
        self, _name, use_checkpointer, should_check_checkpoint
    ):
        """
        When use_checkpointer=False (subagent), _init_or_update_state should skip
        checkpoint state lookup and go directly to initial state.
        """
        runner, mock_graph = self._create_runner(use_checkpointer)

        mock_state = MagicMock()
        mock_state.values = {"messages": []}
        mock_state.next = None
        mock_graph.aget_state = AsyncMock(return_value=mock_state)

        with patch("ee.hogai.core.runner.is_cloud", return_value=False):
            await runner._init_or_update_state()

        if should_check_checkpoint:
            mock_graph.aget_state.assert_called()
        else:
            mock_graph.aget_state.assert_not_called()

    async def test_subagent_callback_handler_uses_parent_span_id(self):
        """
        When parent_span_id is provided, SubagentCallbackHandler should be used
        to nest all events under the parent span.
        """
        from uuid import uuid4

        from ee.hogai.core.runner import SubagentCallbackHandler

        parent_span_id = uuid4()

        with (
            patch("ee.hogai.core.runner.is_cloud", return_value=False),
            patch("ee.hogai.core.runner.posthoganalytics") as mock_posthog,
        ):
            mock_client = MagicMock()
            mock_posthog.default_client = mock_client

            from ee.hogai.core.runner import BaseAgentRunner

            mock_graph = MagicMock()
            mock_stream_processor = MagicMock()

            class TestRunner(BaseAgentRunner):
                def get_initial_state(self):
                    return AssistantState(messages=[])

                def get_resumed_state(self):
                    return PartialAssistantState(messages=[])

            runner = TestRunner(
                team=self.team,
                conversation=self.conversation,
                user=self.user,
                graph_class=cast(type[BaseAssistantGraph], mock_graph),
                state_type=AssistantState,
                partial_state_type=PartialAssistantState,
                stream_processor=mock_stream_processor,
                use_checkpointer=False,
                parent_span_id=parent_span_id,
            )

            # Check that SubagentCallbackHandler was used
            assert len(runner._callback_handlers) == 1
            assert isinstance(runner._callback_handlers[0], SubagentCallbackHandler)
            handler = cast(SubagentCallbackHandler, runner._callback_handlers[0])
            assert handler._parent_span_id == parent_span_id
