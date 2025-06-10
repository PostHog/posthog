from collections.abc import AsyncGenerator
import dataclasses
import json
from collections.abc import Callable
import pytest
import uuid
from unittest.mock import patch
from posthog.temporal.ai.session_summary.summarize_session import (
    stream_llm_summary_activity,
    SessionSummaryInputs,
    SummarizeSessionWorkflow,
)
from temporalio.testing import WorkflowEnvironment
from ee.session_recordings.session_summary.utils import serialize_to_sse_event
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk, Choice, ChoiceDelta
from openai.types.completion_usage import CompletionUsage
from posthog.redis import get_client
from posthog.temporal.ai.session_summary import WORKFLOWS, ACTIVITIES
from temporalio.worker import Worker, UnsandboxedWorkflowRunner
from posthog import constants


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
def session_summary_inputs(
    mock_user,
    mock_events_mapping,
    mock_events_columns,
    mock_url_mapping_reversed,
    mock_window_mapping_reversed,
) -> Callable:
    def _create_inputs(session_id: str) -> SessionSummaryInputs:
        return SessionSummaryInputs(
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


@pytest.fixture
def redis_test_setup():
    """Context manager for Redis test setup and cleanup."""

    class RedisTestContext:
        def __init__(self):
            self.redis_client = get_client()
            self.keys_to_cleanup = []

        def setup_input_data(self, input_key: str, output_key: str, input_data: SessionSummaryInputs):
            """Set up Redis input data and track keys for cleanup."""
            self.redis_client.setex(
                input_key,
                900,  # 15 minutes TTL
                json.dumps(
                    {
                        "input_data": dataclasses.asdict(input_data),
                        "output_key": output_key,
                    }
                ),
            )
            self.keys_to_cleanup.extend([input_key, output_key])

        def cleanup(self):
            """Clean up all tracked Redis keys."""
            for key in self.keys_to_cleanup:
                self.redis_client.delete(key)

    context = RedisTestContext()
    try:
        yield context
    finally:
        context.cleanup()


class TestStreamLlmSummaryActivity:
    @pytest.mark.asyncio
    async def test_stream_llm_summary_activity_standalone(
        self,
        mocker,
        mock_enriched_llm_json_response,
        mock_stream_llm,
        session_summary_inputs,
        redis_test_setup,
    ):
        # Prepare Redis data
        session_id = "test_session_id"
        input_data = session_summary_inputs(session_id)
        redis_input_key = "test_input_key"
        redis_output_key = "test_output_key"
        # Set up spies to track Redis operations
        spy_get = mocker.spy(redis_test_setup.redis_client, "get")
        spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
        # Store initial input data
        redis_test_setup.setup_input_data(redis_input_key, redis_output_key, input_data)
        # Run the activity and verify results
        expected_final_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=json.dumps(mock_enriched_llm_json_response)
        )
        with (
            patch("ee.session_recordings.session_summary.llm.consume.stream_llm", return_value=mock_stream_llm()),
            patch("temporalio.activity.heartbeat") as mock_heartbeat,
        ):
            # Call the activity directly as a function
            result = await stream_llm_summary_activity(redis_input_key)
            # Verify the result is the final SSE event
            assert result == expected_final_summary
            # Verify heartbeat was called
            assert mock_heartbeat.call_count >= 1
            # Verify Redis operations count
            assert spy_get.call_count == 1  # Get input data
            # Initial setup and number of valid chunks (unparseable chunks are skipped)
            assert spy_setex.call_count == 1 + 8


class TestSummarizeSessionWorkflow:
    @pytest.mark.asyncio
    async def test_summarize_session_workflow(
        self,
        mocker,
        mock_enriched_llm_json_response,
        mock_stream_llm,
        session_summary_inputs,
        redis_test_setup,
    ):
        # Prepare test data
        session_id = "test_workflow_session_id"
        input_data = session_summary_inputs(session_id)
        redis_input_key = f"test_workflow_input_key_{uuid.uuid4()}"
        redis_output_key = f"test_workflow_output_key_{uuid.uuid4()}"
        # Store input data in Redis
        redis_test_setup.setup_input_data(redis_input_key, redis_output_key, input_data)
        expected_final_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=json.dumps(mock_enriched_llm_json_response)
        )
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
                    # Wait for workflow to complete and get result
                    workflow_id = f"test_workflow_{uuid.uuid4()}"
                    result = await activity_environment.client.execute_workflow(
                        SummarizeSessionWorkflow.run,
                        redis_input_key,
                        id=workflow_id,
                        task_queue=worker.task_queue,
                    )
                    # Verify the workflow returns the expected result
                    assert result == expected_final_summary
