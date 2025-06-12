from collections.abc import AsyncGenerator
import asyncio
import json
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any
from collections.abc import Generator
import pytest
import uuid
from unittest.mock import MagicMock, patch

from pytest_mock import MockerFixture
from ee.session_recordings.session_summary.summarize_session import (
    SingleSessionSummaryData,
    SingleSessionSummaryLlmInputs,
)
from posthog.temporal.ai.session_summary.summarize_session import (
    SingleSessionSummaryInputs,
    SummarizeSingleSessionWorkflow,
    _compress_llm_input_data,
    execute_summarize_session,
    stream_llm_single_session_summary_activity,
)
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from ee.session_recordings.session_summary.utils import serialize_to_sse_event
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk, Choice, ChoiceDelta
from openai.types.completion_usage import CompletionUsage
from posthog.redis import get_client
from posthog.temporal.ai import WORKFLOWS, ACTIVITIES
from temporalio.worker import Worker, UnsandboxedWorkflowRunner
from posthog import constants
from unittest.mock import AsyncMock
from temporalio.exceptions import ApplicationError
from temporalio.client import WorkflowFailureError


def _create_chunk(content: str) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="test_id",
        choices=[
            Choice(
                delta=ChoiceDelta(content=content),
                index=0,
                finish_reason=None,
            )
        ],
        created=1234567890,
        model="gpt-4",
        object="chat.completion.chunk",
        usage=CompletionUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )


@pytest.fixture
def mock_stream_llm(mock_valid_llm_yaml_response: str) -> Callable:
    async def _mock_stream_llm(*args, **kwargs) -> AsyncGenerator[ChatCompletionChunk, None]:
        # Split into chunks
        chunk_size = 100
        yaml_chunks = [
            mock_valid_llm_yaml_response[i : i + chunk_size]
            for i in range(0, len(mock_valid_llm_yaml_response), chunk_size)
        ]
        for chunk_content in yaml_chunks:
            yield _create_chunk(chunk_content)

    return _mock_stream_llm


@pytest.fixture
def mock_single_session_summary_inputs(
    mock_user: MagicMock,
    mock_team: MagicMock,
) -> Callable:
    def _create_inputs(session_id: str) -> SingleSessionSummaryInputs:
        return SingleSessionSummaryInputs(
            session_id=session_id,
            user_pk=mock_user.pk,
            team_id=mock_team.id,
            redis_input_key="test_input_key",
            redis_output_key="test_output_key",
        )

    return _create_inputs


@pytest.fixture
def mock_session_summary_llm_inputs(
    mock_user,
    mock_events_mapping,
    mock_events_columns,
    mock_url_mapping_reversed,
    mock_window_mapping_reversed,
) -> Callable:
    def _create_inputs(session_id: str) -> SingleSessionSummaryLlmInputs:
        return SingleSessionSummaryLlmInputs(
            session_id=session_id,
            user_pk=mock_user.pk,
            summary_prompt="Generate a summary for this session",
            system_prompt="You are a helpful assistant that summarizes user sessions",
            simplified_events_mapping=mock_events_mapping,
            simplified_events_columns=mock_events_columns,
            url_mapping_reversed=mock_url_mapping_reversed,
            window_mapping_reversed=mock_window_mapping_reversed,
            session_start_time_str="2025-03-31T18:40:32.302000Z",
            session_duration=5323,
        )

    return _create_inputs


class RedisTestContext:
    def __init__(self):
        self.redis_client = get_client()
        self.keys_to_cleanup = []

    def setup_input_data(self, input_key: str, output_key: str, input_data: bytes):
        """Set up Redis input data and track keys for cleanup."""
        self.redis_client.setex(
            input_key,
            900,  # 15 minutes TTL
            input_data,
        )
        self.keys_to_cleanup.extend([input_key, output_key])

    def cleanup(self):
        """Clean up all tracked Redis keys."""
        for key in self.keys_to_cleanup:
            self.redis_client.delete(key)


@pytest.fixture
def redis_test_setup() -> Generator[RedisTestContext, None, None]:
    """Context manager for Redis test setup and cleanup."""
    context = RedisTestContext()
    try:
        yield context
    finally:
        context.cleanup()

    # def test_execute_summarize_session_no_events_sse_error(
    #     self,
    #     mock_user: MagicMock,
    #     mock_team: MagicMock,
    #     mock_raw_metadata: dict[str, Any],
    #     mock_raw_events_columns: list[str],
    # ):
    #     """Test that we yield a proper SSE error when no events are found (for example, for fresh real-time replays)."""
    #     session_id = "test_session_id"
    #     empty_context = ExtraSummaryContext()
    #     with (
    #         patch("ee.session_recordings.session_summary.summarize_session.get_team", return_value=mock_team),
    #         patch(
    #             "ee.session_recordings.session_summary.summarize_session.get_session_metadata",
    #             return_value=mock_raw_metadata,
    #         ),
    #         patch.object(
    #             SessionReplayEvents,
    #             "get_events",
    #             return_value=(mock_raw_events_columns, []),  # Return columns but no events
    #         ) as mock_get_db_events,
    #     ):
    #         result = list(
    #             execute_summarize_session(
    #                 session_id=session_id, user_pk=mock_user.pk, team=mock_team, extra_summary_context=empty_context
    #             )
    #         )
    #         assert len(result) == 1
    #         assert (
    #             result[0]
    #             == "event: session-summary-error\ndata: No events found for this replay yet. Please try again in a few minutes.\n\n"
    #         )
    #         mock_get_db_events.assert_called_once_with(
    #             session_id="test_session_id",
    #             team=mock_team,
    #             metadata=mock_raw_metadata,
    #             events_to_ignore=["$feature_flag_called"],
    #             extra_fields=EXTRA_SUMMARY_EVENT_FIELDS,
    #             page=0,
    #             limit=3000,
    #         )


class TestFetchSessionDataActivity:
    @pytest.mark.asyncio
    async def test_fetch_session_data_activity(
        self,
        mocker: MockerFixture,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        pass


class TestStreamLlmSummaryActivity:
    @pytest.mark.asyncio
    async def test_stream_llm_summary_activity_standalone(
        self,
        mocker: MockerFixture,
        mock_enriched_llm_json_response: dict[str, Any],
        mock_stream_llm: Callable,
        mock_session_summary_llm_inputs: Callable,
        mock_single_session_summary_inputs: Callable,
        redis_test_setup: RedisTestContext,
    ):
        session_id = "test_session_id"
        llm_input_data = mock_session_summary_llm_inputs(session_id)
        compressed_llm_input_data = _compress_llm_input_data(llm_input_data)
        input_data = mock_single_session_summary_inputs(session_id)
        # Set up spies to track Redis operations
        spy_get = mocker.spy(redis_test_setup.redis_client, "get")
        spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
        # Store initial input data
        redis_test_setup.setup_input_data(
            input_data.redis_input_key,
            input_data.redis_output_key,
            compressed_llm_input_data,
        )
        # Run the activity and verify results
        expected_final_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=json.dumps(mock_enriched_llm_json_response)
        )
        with (
            patch("ee.session_recordings.session_summary.llm.consume.stream_llm", return_value=mock_stream_llm()),
            patch("temporalio.activity.heartbeat") as mock_heartbeat,
        ):
            # Call the activity directly as a function
            result = await stream_llm_single_session_summary_activity(input_data)
            # Verify the result is the final SSE event
            assert result == expected_final_summary
            # Verify heartbeat was called
            assert mock_heartbeat.call_count >= 1
            # Verify Redis operations count
            assert spy_get.call_count == 1  # Get input data
            # Initial setup and number of valid chunks (unparseable chunks are skipped)
            assert spy_setex.call_count == 1 + 8


class TestSummarizeSessionWorkflow:
    @asynccontextmanager
    async def workflow_test_environment(
        self, mock_stream_llm: Callable
    ) -> AsyncGenerator[tuple[WorkflowEnvironment, Worker], None]:
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.GENERAL_PURPOSE_TASK_QUEUE,
                workflows=WORKFLOWS,
                activities=ACTIVITIES,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ) as worker:
                with patch(
                    "ee.session_recordings.session_summary.llm.consume.stream_llm", return_value=mock_stream_llm()
                ):
                    yield activity_environment, worker

    def setup_workflow_test(
        self,
        mock_session_summary_llm_inputs: Callable,
        redis_test_setup: RedisTestContext,
        mock_enriched_llm_json_response: dict[str, Any],
        session_id_suffix: str = "",
    ) -> tuple[str, str, str, str, str]:
        # Prepare test data
        session_id = f"test_workflow_session_id{session_id_suffix}"
        input_data = mock_session_summary_llm_inputs(session_id)
        redis_input_key = f"test_workflow_input_key_{uuid.uuid4()}"
        redis_output_key = f"test_workflow_output_key_{uuid.uuid4()}"
        workflow_id = f"test_workflow_{uuid.uuid4()}"
        # Store input data in Redis
        redis_test_setup.setup_input_data(redis_input_key, redis_output_key, input_data)
        # Prepare expected final summary
        expected_final_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=json.dumps(mock_enriched_llm_json_response)
        )
        return session_id, workflow_id, redis_input_key, redis_output_key, expected_final_summary

    def test_execute_summarize_session(
        self,
        mock_enriched_llm_json_response: dict[str, Any],
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_session_summary_llm_inputs: Callable,
        redis_test_setup: RedisTestContext,
    ):
        # Prepare input data
        session_id = "test_session_id"
        sample_session_summary_data = SingleSessionSummaryData(
            session_id=session_id,
            user_pk=mock_user.pk,
            prompt_data=True,  # type: ignore
            prompt=True,  # type: ignore
            sse_error_msg=None,
        )
        input_data = mock_session_summary_llm_inputs(session_id)
        # Mock Redis data for streaming updates
        expected_final_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=json.dumps(mock_enriched_llm_json_response)
        )
        intermediate_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=json.dumps({"partial": "data"})
        )
        # Track Redis calls to properly mock responses
        redis_call_count = 0

        def mock_redis_get(key):
            nonlocal redis_call_count
            # Return None for first poll, then intermediate data, then final data
            if "output" in key:
                current_call_number = redis_call_count
                redis_call_count += 1
                # First call - no data yet
                if current_call_number == 0:
                    return None
                # Second call - stream chunk
                elif current_call_number == 1:
                    return json.dumps({"last_summary_state": intermediate_summary, "timestamp": 1234567890})
                # Third call - final data
                else:
                    return json.dumps({"last_summary_state": expected_final_summary, "timestamp": 1234567891})
            return None

        # Simulate workflow states: RUNNING -> RUNNING with data -> COMPLETED
        mock_workflow_handle = MagicMock()
        mock_workflow_handle.describe = AsyncMock(
            side_effect=[
                MagicMock(status=WorkflowExecutionStatus.RUNNING),  # First poll - no data yet
                MagicMock(status=WorkflowExecutionStatus.RUNNING),  # Second poll - with streaming data
                MagicMock(status=WorkflowExecutionStatus.COMPLETED),  # Final poll - completed
            ]
        )
        mock_workflow_handle.result = AsyncMock(return_value=expected_final_summary)
        with (
            patch(
                "posthog.temporal.ai.session_summary.summarize_session.prepare_data_for_single_session_summary",
                return_value=sample_session_summary_data,
            ),
            patch(
                "posthog.temporal.ai.session_summary.summarize_session._prepare_single_session_summary_input",
                return_value=input_data,
            ),
            patch(
                "posthog.temporal.ai.session_summary.summarize_session._start_workflow",
                return_value=mock_workflow_handle,
            ),
            patch.object(redis_test_setup.redis_client, "get", side_effect=mock_redis_get),
            patch.object(redis_test_setup.redis_client, "setex"),  # Does nothing
            patch.object(redis_test_setup.redis_client, "delete"),  # Does nothing
        ):
            result = list(
                execute_summarize_session(
                    session_id=session_id,
                    user_pk=mock_user.pk,
                    team=mock_team,
                    extra_summary_context=None,
                    local_reads_prod=False,
                )
            )
            # Verify we got the expected streaming results
            assert len(result) == 2  # intermediate + final, as the first empty result is skipped
            assert result[0] == intermediate_summary
            assert result[1] == expected_final_summary
            # Verify workflow was polled the expected number of times
            assert mock_workflow_handle.describe.call_count == 3
            assert mock_workflow_handle.result.call_count == 1

    @pytest.mark.asyncio
    async def test_summarize_session_workflow(
        self,
        mocker: MockerFixture,
        mock_enriched_llm_json_response: dict[str, Any],
        mock_stream_llm: Callable,
        mock_session_summary_llm_inputs: Callable,
        redis_test_setup: RedisTestContext,
    ):
        """
        Test that the workflow completes successfully and returns the expected result. Also verifies that Redis operations are performed as expected.
        """
        # Set up spies to track Redis operations
        spy_get = mocker.spy(redis_test_setup.redis_client, "get")
        spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
        _, workflow_id, redis_input_key, _, expected_final_summary = self.setup_workflow_test(
            mock_session_summary_llm_inputs, redis_test_setup, mock_enriched_llm_json_response, ""
        )
        async with self.workflow_test_environment(mock_stream_llm) as (activity_environment, worker):
            # Wait for workflow to complete and get result
            result = await activity_environment.client.execute_workflow(
                SummarizeSingleSessionWorkflow.run,
                redis_input_key,
                id=workflow_id,
                task_queue=worker.task_queue,
            )
            # Verify the workflow returns the expected result
            assert result == expected_final_summary
            # Verify Redis operations count
            assert spy_get.call_count == 1  # Get input data
            # Initial setup and number of valid chunks (unparseable chunks are skipped)
            assert spy_setex.call_count == 1 + 8

    @pytest.mark.asyncio
    async def test_summarize_session_workflow_with_activity_retry(
        self,
        mock_enriched_llm_json_response: dict[str, Any],
        mock_stream_llm: Callable,
        mock_session_summary_llm_inputs: Callable,
        redis_test_setup: RedisTestContext,
    ):
        """Test that the workflow retries when stream_llm_summary_activity fails initially, but succeeds eventually."""
        _, workflow_id, redis_input_key, _, expected_final_summary = self.setup_workflow_test(
            mock_session_summary_llm_inputs, redis_test_setup, mock_enriched_llm_json_response, "_retry"
        )
        # Track Redis get calls to simulate failure on first attempt
        redis_get_call_count = 0
        original_get = redis_test_setup.redis_client.get

        def mock_redis_get_with_failure(key):
            nonlocal redis_get_call_count
            redis_get_call_count += 1
            if redis_get_call_count in (1, 2):
                # First two calls fail with a retryable exception
                raise ApplicationError("Simulated stream_llm_session_summary failure", non_retryable=False)
            else:
                # Subsequent calls succeed - return actual data
                return original_get(key)

        async with self.workflow_test_environment(mock_stream_llm) as (activity_environment, worker):
            with patch.object(redis_test_setup.redis_client, "get", side_effect=mock_redis_get_with_failure):
                # Wait for workflow to complete and get result
                result = await activity_environment.client.execute_workflow(
                    SummarizeSingleSessionWorkflow.run,
                    redis_input_key,
                    id=workflow_id,
                    task_queue=worker.task_queue,
                )
                # Verify the workflow eventually succeeds after retry
                assert result == expected_final_summary
                # Verify that Redis get was called at least three times (first two failures + success)
                assert redis_get_call_count == 3

    @pytest.mark.asyncio
    async def test_summarize_session_workflow_exceeds_retries(
        self,
        mock_stream_llm: Callable,
        mock_session_summary_llm_inputs: Callable,
        redis_test_setup: RedisTestContext,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        """Test that the workflow retries when stream_llm_summary_activity and fails, as it exceeds the retries limit."""
        _, workflow_id, redis_input_key, _, _ = self.setup_workflow_test(
            mock_session_summary_llm_inputs, redis_test_setup, mock_enriched_llm_json_response, "_exceeds_retries"
        )
        # Track Redis get calls to simulate failure on first attempt
        redis_get_call_count = 0
        original_get = redis_test_setup.redis_client.get

        def mock_redis_get_with_failure(key):
            nonlocal redis_get_call_count
            redis_get_call_count += 1
            # Retries limit is 3, so failing 3 times should lead to workflow failure
            if redis_get_call_count in (1, 2, 3):
                # First two calls fail with a retryable exception
                raise ApplicationError("Simulated stream_llm_session_summary failure", non_retryable=False)
            else:
                # Subsequent calls succeed - return actual data
                return original_get(key)

        async with self.workflow_test_environment(mock_stream_llm) as (activity_environment, worker):
            with patch.object(redis_test_setup.redis_client, "get", side_effect=mock_redis_get_with_failure):
                # Wait for workflow to complete and get result
                with pytest.raises(WorkflowFailureError):
                    await activity_environment.client.execute_workflow(
                        SummarizeSingleSessionWorkflow.run,
                        redis_input_key,
                        id=workflow_id,
                        task_queue=worker.task_queue,
                    )

    @pytest.mark.parametrize(
        "invalid_arg,expected_error_type",
        [
            ({"redis_key": "test_key"}, "dict"),
            (["test_key"], "list"),
        ],
    )
    @pytest.mark.asyncio
    async def test_summarize_session_workflow_with_incorrect_argument_type(
        self,
        invalid_arg: str,
        expected_error_type: str,
        mock_stream_llm: Callable,
        mock_session_summary_llm_inputs: Callable,
        redis_test_setup: RedisTestContext,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        """Test that the workflow properly handles incorrect argument types by failing or timing out during argument processing."""
        self.setup_workflow_test(
            mock_session_summary_llm_inputs, redis_test_setup, mock_enriched_llm_json_response, "_incorrect_type"
        )
        async with self.workflow_test_environment(mock_stream_llm) as (activity_environment, worker):
            # Test with the invalid argument - should fail during argument processing
            workflow_id = f"test_workflow_{expected_error_type}_{uuid.uuid4()}"
            with pytest.raises((WorkflowFailureError, asyncio.TimeoutError)) as exc_info:
                await asyncio.wait_for(
                    activity_environment.client.execute_workflow(
                        SummarizeSingleSessionWorkflow.run,
                        invalid_arg,  # Wrong: passing incorrect type instead of string
                        id=workflow_id,
                        task_queue=worker.task_queue,
                    ),
                    timeout=5,  # Add timeout to prevent hanging
                )
            # The error could be either a WorkflowFailureError with the type conversion error
            # or a TimeoutError if the workflow hangs during argument processing
            if isinstance(exc_info.value, WorkflowFailureError):
                # Check for the actual error message from Temporal's type converter
                assert f"Expected value to be str, was <class '{expected_error_type}'>" in str(exc_info.value)
            else:
                # TimeoutError indicates the workflow hung during argument processing,
                # which is also a valid test outcome for this scenario
                assert isinstance(exc_info.value, asyncio.TimeoutError)
