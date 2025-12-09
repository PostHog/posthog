from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import anthropic
from parameterized import parameterized

from posthog.schema import AssistantEventType, FailureMessage

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
            graph=mock_graph,
            state_type=AssistantState,
            partial_state_type=PartialAssistantState,
            mode=MagicMock(value="assistant"),
            stream_processor=mock_stream_processor,
        )

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
            self.assertEqual(len(results), 1)
            event_type, message = results[0]
            self.assertEqual(event_type, AssistantEventType.MESSAGE)
            self.assertIsInstance(message, FailureMessage)
            self.assertEqual(
                message.content,
                "I'm unable to respond right now due to a temporary service issue. Please try again later.",
            )

            # Verify state was reset
            mock_graph.aupdate_state.assert_called()

            # Verify Prometheus counter was incremented with correct provider
            mock_counter.labels.assert_called_with(provider=expected_provider)
            mock_counter.labels.return_value.inc.assert_called_once()

            # Verify error was logged
            mock_logger.exception.assert_called_once()
            call_args = mock_logger.exception.call_args
            self.assertEqual(call_args[0][0], "llm_provider_error")
            self.assertEqual(call_args[1]["provider"], expected_provider)

            # Verify exception was captured
            mock_posthog.capture_exception.assert_called_once()
            capture_call_args = mock_posthog.capture_exception.call_args
            self.assertEqual(capture_call_args[1]["properties"]["error_type"], "llm_provider_error")
            self.assertEqual(capture_call_args[1]["properties"]["provider"], expected_provider)
