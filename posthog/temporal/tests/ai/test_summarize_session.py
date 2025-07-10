from collections.abc import AsyncGenerator
import asyncio
import dataclasses
import json
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any
import pytest
import uuid
from unittest.mock import MagicMock, patch

from pytest_mock import MockerFixture

from ee.session_recordings.session_summary import ExceptionToRetry
from ee.session_recordings.session_summary.prompt_data import SessionSummaryPromptData
from ee.session_recordings.session_summary.summarize_session import (
    SingleSessionSummaryData,
    SingleSessionSummaryLlmInputs,
)
from posthog.temporal.ai.session_summary.state import (
    StateActivitiesEnum,
    _compress_redis_data,
    generate_state_key,
    get_data_class_from_redis,
    get_redis_state_client,
)
from posthog.temporal.ai.session_summary.summarize_session import (
    SummarizeSingleSessionWorkflow,
    execute_summarize_session_stream,
    stream_llm_single_session_summary_activity,
)
from posthog.temporal.ai.session_summary.shared import fetch_session_data_activity
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from ee.session_recordings.session_summary.utils import serialize_to_sse_event
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk, Choice, ChoiceDelta
from openai.types.completion_usage import CompletionUsage
from posthog.temporal.ai import WORKFLOWS
from temporalio.worker import Worker, UnsandboxedWorkflowRunner
from posthog import constants
from unittest.mock import AsyncMock
from temporalio.exceptions import ApplicationError
from temporalio.client import WorkflowFailureError

from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.tests.ai.conftest import AsyncRedisTestContext, SyncRedisTestContext

pytestmark = pytest.mark.django_db


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


class TestFetchSessionDataActivity:
    @pytest.mark.asyncio
    async def test_fetch_session_data_activity_standalone(
        self,
        mocker: MockerFixture,
        mock_session_id: str,
        mock_single_session_summary_inputs: Callable,
        mock_team: MagicMock,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        redis_test_setup: AsyncRedisTestContext,
    ):
        """Test that fetch_session_data_activity stores compressed data correctly in Redis."""
        key_base = "fetch-session-data-activity-standalone"
        input_data = mock_single_session_summary_inputs(mock_session_id, key_base)
        redis_input_key = generate_state_key(
            key_base=key_base, label=StateActivitiesEnum.SESSION_DB_DATA, state_id=mock_session_id
        )
        # Set up a spy to track Redis operations
        spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
        with (
            # Mock DB calls
            patch("ee.session_recordings.session_summary.input_data.get_team", return_value=mock_team),
            patch(
                "ee.session_recordings.session_summary.summarize_session.get_session_metadata",
                return_value=mock_raw_metadata,
            ),
            patch(
                "ee.session_recordings.session_summary.summarize_session.get_session_events",
                return_value=(mock_raw_events_columns, mock_raw_events),
            ),
        ):
            # Call the activity directly as a function, success if no exception is raised
            await fetch_session_data_activity(input_data)
            # Verify Redis operations
            assert spy_setex.call_count == 1  # Store compressed data
            # Verify the data was stored correctly
            stored_data = await redis_test_setup.redis_client.get(redis_input_key)
            assert stored_data is not None
            # Verify we can decompress and parse the stored data
            decompressed_data = await get_data_class_from_redis(
                redis_client=redis_test_setup.redis_client,
                redis_key=redis_input_key,
                label=StateActivitiesEnum.SESSION_DB_DATA,
                target_class=SingleSessionSummaryLlmInputs,
            )
            assert decompressed_data.session_id == mock_session_id
            assert decompressed_data.user_id == input_data.user_id

    @pytest.mark.asyncio
    async def test_fetch_session_data_activity_no_events_raises_error(
        self,
        mock_single_session_summary_inputs: Callable,
        mock_session_id: str,
        mock_team: MagicMock,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
    ):
        """Test that fetch_session_data_activity raises ApplicationError when no events are found (e.g., for fresh real-time replays)."""
        input_data = mock_single_session_summary_inputs(mock_session_id, "test-no-events-key-base")
        with (
            # Mock DB calls - return columns but no events (empty list)
            patch("ee.session_recordings.session_summary.input_data.get_team", return_value=mock_team),
            patch(
                "ee.session_recordings.session_summary.summarize_session.get_session_metadata",
                return_value=mock_raw_metadata,
            ),
            patch(
                "ee.session_recordings.session_summary.summarize_session.get_session_events",
                return_value=(mock_raw_events_columns, []),  # Return columns but no events
            ),
        ):
            with patch("posthog.temporal.ai.session_summary.shared.logger.exception") as mock_logger_exception:
                # Call the activity and expect an ExceptionToRetry to be raised
                with pytest.raises(ExceptionToRetry):
                    await fetch_session_data_activity(input_data)
                # Verify that the logger was called with the expected message
                mock_logger_exception.assert_called_once()
                logged_message = mock_logger_exception.call_args[0][0]
                assert "No events found for this replay yet" in logged_message


class TestStreamLlmSummaryActivity:
    @pytest.mark.asyncio
    async def test_stream_llm_single_session_summary_activity_standalone(
        self,
        mocker: MockerFixture,
        mock_enriched_llm_json_response: dict[str, Any],
        mock_stream_llm: Callable,
        mock_single_session_summary_llm_inputs: Callable,
        mock_single_session_summary_inputs: Callable,
        mock_session_id: str,
        redis_test_setup: AsyncRedisTestContext,
    ):
        llm_input_data = mock_single_session_summary_llm_inputs(mock_session_id)
        compressed_llm_input_data = _compress_redis_data(json.dumps(dataclasses.asdict(llm_input_data)))
        key_base = "stream_llm_test_base"
        input_data = mock_single_session_summary_inputs(mock_session_id, key_base)
        # Generate Redis keys
        _, redis_input_key, redis_output_key = get_redis_state_client(
            key_base=key_base,
            input_label=StateActivitiesEnum.SESSION_DB_DATA,
            output_label=StateActivitiesEnum.SESSION_SUMMARY,
            state_id=mock_session_id,
        )
        assert redis_input_key
        assert redis_output_key
        # Set up spies to track Redis operations
        spy_get = mocker.spy(redis_test_setup.redis_client, "get")
        spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
        # Store initial input data
        await redis_test_setup.setup_input_data(
            compressed_llm_input_data,
            redis_input_key,
            redis_output_key,
        )
        # Run the activity and verify results
        expected_final_summary = json.dumps(mock_enriched_llm_json_response)
        with (
            patch("ee.session_recordings.session_summary.llm.consume.stream_llm", return_value=mock_stream_llm()),
            patch("temporalio.activity.heartbeat") as mock_heartbeat,
            patch("temporalio.activity.info") as mock_activity_info,
        ):
            mock_activity_info.return_value.workflow_id = "test_workflow_id"
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


class TestSummarizeSingleSessionWorkflow:
    @asynccontextmanager
    async def workflow_test_environment(
        self,
        mock_stream_llm: Callable,
        mock_team: MagicMock,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        mock_valid_event_ids: list[str],
    ) -> AsyncGenerator[tuple[WorkflowEnvironment, Worker], None]:
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=constants.MAX_AI_TASK_QUEUE,
                workflows=WORKFLOWS,
                activities=[stream_llm_single_session_summary_activity, fetch_session_data_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ) as worker:
                with (
                    # Mock LLM call
                    patch(
                        "ee.session_recordings.session_summary.llm.consume.stream_llm", return_value=mock_stream_llm()
                    ),
                    # Mock DB calls
                    patch("ee.session_recordings.session_summary.input_data.get_team", return_value=mock_team),
                    patch(
                        "ee.session_recordings.session_summary.summarize_session.get_session_metadata",
                        return_value=mock_raw_metadata,
                    ),
                    patch(
                        "ee.session_recordings.session_summary.summarize_session.get_session_events",
                        return_value=(mock_raw_events_columns, mock_raw_events),
                    ),
                    # Mock deterministic hex generation
                    patch.object(
                        SessionSummaryPromptData, "_get_deterministic_hex", side_effect=iter(mock_valid_event_ids)
                    ),
                ):
                    yield activity_environment, worker

    async def setup_workflow_test(
        self,
        mock_session_id: str,
        mock_single_session_summary_llm_inputs: Callable,
        mock_single_session_summary_inputs: Callable,
        redis_test_setup: AsyncRedisTestContext,
        mock_enriched_llm_json_response: dict[str, Any],
    ) -> tuple[str, str, SingleSessionSummaryInputs, str, str]:
        # Prepare test data
        session_id = mock_session_id
        llm_input_data = mock_single_session_summary_llm_inputs(session_id)
        compressed_llm_input_data = _compress_redis_data(json.dumps(dataclasses.asdict(llm_input_data)))
        redis_key_base = f"test_workflow_key_base_{uuid.uuid4()}"
        workflow_id = f"test_workflow_{uuid.uuid4()}"
        # Create workflow input object
        workflow_input = mock_single_session_summary_inputs(session_id, redis_key_base)
        # Generate Redis keys
        _, redis_input_key, redis_output_key = get_redis_state_client(
            key_base=redis_key_base,
            input_label=StateActivitiesEnum.SESSION_DB_DATA,
            output_label=StateActivitiesEnum.SESSION_SUMMARY,
            state_id=session_id,
        )
        assert redis_input_key
        assert redis_output_key
        # Store input data in Redis
        await redis_test_setup.setup_input_data(compressed_llm_input_data, redis_input_key, redis_output_key)
        # Prepare expected final summary
        expected_final_summary = json.dumps(mock_enriched_llm_json_response)
        if session_id != mock_session_id:
            expected_final_summary = expected_final_summary.replace(mock_session_id, session_id)
        expected_sse_final_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=expected_final_summary
        )
        return session_id, workflow_id, workflow_input, expected_final_summary, expected_sse_final_summary

    def test_execute_summarize_session_stream(
        self,
        mock_enriched_llm_json_response: dict[str, Any],
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_single_session_summary_llm_inputs: Callable,
        sync_redis_test_setup: SyncRedisTestContext,
    ):
        # Prepare input data
        sample_session_summary_data = SingleSessionSummaryData(
            session_id=mock_session_id,
            user_id=mock_user.id,
            prompt_data=True,  # type: ignore
            prompt=True,  # type: ignore
            error_msg=None,
        )
        input_data = mock_single_session_summary_llm_inputs(mock_session_id)
        # Mock Redis data for streaming updates
        expected_final_summary = json.dumps(mock_enriched_llm_json_response)
        expected_sse_final_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=expected_final_summary
        )
        intermediate_summary = json.dumps({"partial": "data"})
        intermediate_sse_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=intermediate_summary
        )
        # Track Redis calls to properly mock responses
        redis_call_count = 0

        def mock_redis_get(key: str) -> str | None:
            nonlocal redis_call_count
            # Return None for first poll, then intermediate data, then final data
            if "session_summary" in key:
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
                "ee.session_recordings.session_summary.summarize_session.prepare_data_for_single_session_summary",
                return_value=sample_session_summary_data,
            ),
            patch(
                "ee.session_recordings.session_summary.summarize_session.prepare_single_session_summary_input",
                return_value=input_data,
            ),
            patch(
                "posthog.temporal.ai.session_summary.summarize_session._start_workflow",
                return_value=mock_workflow_handle,
            ),
            patch.object(sync_redis_test_setup.redis_client, "get", side_effect=mock_redis_get),
            patch.object(sync_redis_test_setup.redis_client, "setex"),  # Does nothing
            patch.object(sync_redis_test_setup.redis_client, "delete"),  # Does nothing
        ):
            result = list(
                execute_summarize_session_stream(
                    session_id=mock_session_id,
                    user_id=mock_user.id,
                    team=mock_team,
                    extra_summary_context=None,
                    local_reads_prod=False,
                )
            )
            # Verify we got the expected streaming results
            assert len(result) == 2  # intermediate + final, as the first empty result is skipped
            assert result[0] == intermediate_sse_summary
            assert result[1] == expected_sse_final_summary
            # Verify workflow was polled the expected number of times
            assert mock_workflow_handle.describe.call_count == 3
            assert mock_workflow_handle.result.call_count == 1

    @pytest.mark.asyncio
    async def test_summarize_session_workflow(
        self,
        mocker: MockerFixture,
        mock_session_id: str,
        mock_enriched_llm_json_response: dict[str, Any],
        mock_stream_llm: Callable,
        mock_single_session_summary_llm_inputs: Callable,
        mock_single_session_summary_inputs: Callable,
        mock_team: MagicMock,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        mock_valid_event_ids: list[str],
        redis_test_setup: AsyncRedisTestContext,
    ):
        """
        Test that the workflow completes successfully and returns the expected result. Also verifies that Redis operations are performed as expected.
        """
        # Set up spies to track Redis operations
        spy_get = mocker.spy(redis_test_setup.redis_client, "get")
        spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
        _, workflow_id, workflow_input, expected_final_summary, _ = await self.setup_workflow_test(
            mock_session_id,
            mock_single_session_summary_llm_inputs,
            mock_single_session_summary_inputs,
            redis_test_setup,
            mock_enriched_llm_json_response,
        )
        async with self.workflow_test_environment(
            mock_stream_llm,
            mock_team,
            mock_raw_metadata,
            mock_raw_events_columns,
            mock_raw_events,
            mock_valid_event_ids,
        ) as (activity_environment, worker):
            # Wait for workflow to complete and get result
            result = await activity_environment.client.execute_workflow(
                SummarizeSingleSessionWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=worker.task_queue,
            )
            # Verify the workflow returns the expected result
            assert result == expected_final_summary
            # Verify Redis operations count
            assert spy_get.call_count == 2  # Try to get cached DB data + Get input data from stream activity
            # Store DB data input (no store call in the fetch activity, as it would get it from Redis)
            # + store valid chunks to stream (unparseable chunks are skipped)
            assert spy_setex.call_count == 1 + 8

    @pytest.mark.asyncio
    async def test_summarize_session_workflow_with_activity_retry(
        self,
        mock_session_id: str,
        mock_enriched_llm_json_response: dict[str, Any],
        mock_stream_llm: Callable,
        mock_single_session_summary_llm_inputs: Callable,
        mock_single_session_summary_inputs: Callable,
        mock_team: MagicMock,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        mock_valid_event_ids: list[str],
        redis_test_setup: AsyncRedisTestContext,
    ):
        """Test that the workflow retries when stream_llm_summary_activity fails initially, but succeeds eventually."""
        _, workflow_id, workflow_input, expected_final_summary, _ = await self.setup_workflow_test(
            mock_session_id,
            mock_single_session_summary_llm_inputs,
            mock_single_session_summary_inputs,
            redis_test_setup,
            mock_enriched_llm_json_response,
        )
        # Track Redis get calls to simulate failure on first attempt
        redis_get_call_count = 0
        original_get = redis_test_setup.redis_client.get

        def mock_redis_get_with_failure(key):
            nonlocal redis_get_call_count
            redis_get_call_count += 1
            if redis_get_call_count in (1, 2):
                # First two calls fail with a retryable exception
                raise ApplicationError("Simulated stream_llm_single_session_summary failure", non_retryable=False)
            else:
                # Subsequent calls succeed - return actual data
                return original_get(key)

        async with self.workflow_test_environment(
            mock_stream_llm,
            mock_team,
            mock_raw_metadata,
            mock_raw_events_columns,
            mock_raw_events,
            mock_valid_event_ids,
        ) as (activity_environment, worker):
            with patch.object(redis_test_setup.redis_client, "get", side_effect=mock_redis_get_with_failure):
                # Wait for workflow to complete and get result
                result = await activity_environment.client.execute_workflow(
                    SummarizeSingleSessionWorkflow.run,
                    workflow_input,
                    id=workflow_id,
                    task_queue=worker.task_queue,
                )
                # Verify the workflow eventually succeeds after retry
                assert result == expected_final_summary
                # Verify that Redis get was called four times (first two DB fetch failures + DB fetch success + getting DB data from Redis from stream activity)
                assert redis_get_call_count == 4

    @pytest.mark.asyncio
    async def test_summarize_session_workflow_exceeds_retries(
        self,
        mock_session_id: str,
        mock_stream_llm: Callable,
        mock_single_session_summary_llm_inputs: Callable,
        mock_single_session_summary_inputs: Callable,
        mock_team: MagicMock,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        mock_valid_event_ids: list[str],
        redis_test_setup: AsyncRedisTestContext,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        """Test that the workflow retries when stream_llm_summary_activity and fails, as it exceeds the retries limit."""
        _, workflow_id, workflow_input, _, _ = await self.setup_workflow_test(
            mock_session_id,
            mock_single_session_summary_llm_inputs,
            mock_single_session_summary_inputs,
            redis_test_setup,
            mock_enriched_llm_json_response,
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
                raise ApplicationError("Simulated stream_llm_single_session_summary failure", non_retryable=False)
            else:
                # Subsequent calls succeed - return actual data
                return original_get(key)

        async with self.workflow_test_environment(
            mock_stream_llm,
            mock_team,
            mock_raw_metadata,
            mock_raw_events_columns,
            mock_raw_events,
            mock_valid_event_ids,
        ) as (activity_environment, worker):
            with patch.object(redis_test_setup.redis_client, "get", side_effect=mock_redis_get_with_failure):
                # Wait for workflow to complete and get result
                with pytest.raises(WorkflowFailureError):
                    await activity_environment.client.execute_workflow(
                        SummarizeSingleSessionWorkflow.run,
                        workflow_input,
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
        mock_session_id: str,
        mock_stream_llm: Callable,
        mock_single_session_summary_llm_inputs: Callable,
        mock_single_session_summary_inputs: Callable,
        mock_team: MagicMock,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        mock_valid_event_ids: list[str],
        redis_test_setup: AsyncRedisTestContext,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        """Test that the workflow properly handles incorrect argument types by failing or timing out during argument processing."""
        await self.setup_workflow_test(
            mock_session_id,
            mock_single_session_summary_llm_inputs,
            mock_single_session_summary_inputs,
            redis_test_setup,
            mock_enriched_llm_json_response,
        )
        async with self.workflow_test_environment(
            mock_stream_llm,
            mock_team,
            mock_raw_metadata,
            mock_raw_events_columns,
            mock_raw_events,
            mock_valid_event_ids,
        ) as (activity_environment, worker):
            # Test with the invalid argument - should fail during argument processing
            workflow_id = f"test_workflow_{expected_error_type}_{uuid.uuid4()}"
            with pytest.raises((WorkflowFailureError, asyncio.TimeoutError)) as exc_info:
                await asyncio.wait_for(
                    activity_environment.client.execute_workflow(
                        SummarizeSingleSessionWorkflow.run,
                        # Wrong: passing incorrect type instead of string
                        invalid_arg,  # type: ignore[misc]
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
