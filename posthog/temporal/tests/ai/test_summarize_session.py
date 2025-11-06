import json
import uuid
import asyncio
import dataclasses
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

from openai.types.chat.chat_completion_chunk import ChatCompletionChunk, Choice, ChoiceDelta
from openai.types.completion_usage import CompletionUsage
from pytest_mock import MockerFixture
from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async
from posthog.temporal.ai import WORKFLOWS
from posthog.temporal.ai.session_summary.state import (
    StateActivitiesEnum,
    _compress_redis_data,
    decompress_redis_data,
    generate_state_key,
    get_data_class_from_redis,
    get_redis_state_client,
)
from posthog.temporal.ai.session_summary.summarize_session import (
    SummarizeSingleSessionStreamWorkflow,
    execute_summarize_session_stream,
    fetch_session_data_activity,
    stream_llm_single_session_summary_activity,
)
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.tests.ai.conftest import AsyncRedisTestContext, SyncRedisTestContext

from products.enterprise.backend.hogai.session_summaries import ExceptionToRetry
from products.enterprise.backend.hogai.session_summaries.session.prompt_data import SessionSummaryPromptData
from products.enterprise.backend.hogai.session_summaries.session.summarize_session import (
    SingleSessionSummaryData,
    SingleSessionSummaryLlmInputs,
)
from products.enterprise.backend.hogai.session_summaries.utils import serialize_to_sse_event
from products.enterprise.backend.models.session_summaries import SingleSessionSummary

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
        ateam: Team,
        auser: User,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        redis_test_setup: AsyncRedisTestContext,
    ):
        """Test that fetch_session_data_activity stores compressed data correctly in Redis."""
        key_base = "fetch-session-data-activity-standalone"
        input_data = mock_single_session_summary_inputs(mock_session_id, ateam.id, auser.id, key_base)
        redis_input_key = generate_state_key(
            key_base=key_base, label=StateActivitiesEnum.SESSION_DB_DATA, state_id=mock_session_id
        )
        # Set up a spy to track Redis operations
        spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
        with (
            # Mock DB calls
            patch(
                "products.enterprise.backend.hogai.session_summaries.session.input_data.get_team", return_value=ateam
            ),
            patch(
                "ee.hogai.session_summaries.session.summarize_session.get_session_metadata",
                return_value=mock_raw_metadata,
            ),
            patch(
                "ee.hogai.session_summaries.session.summarize_session.get_session_events",
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
            assert decompressed_data
            assert decompressed_data.session_id == mock_session_id
            assert decompressed_data.user_id == input_data.user_id

    @pytest.mark.asyncio
    async def test_fetch_session_data_activity_no_events_raises_error(
        self,
        mock_single_session_summary_inputs: Callable,
        mock_session_id: str,
        ateam: Team,
        auser: User,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
    ):
        """Test that fetch_session_data_activity raises ApplicationError when no events are found (e.g., for fresh real-time replays)."""
        input_data = mock_single_session_summary_inputs(mock_session_id, ateam.id, auser.id, "test-no-events-key-base")
        with (
            # Mock DB calls - return columns but no events (empty list)
            patch(
                "products.enterprise.backend.hogai.session_summaries.session.input_data.get_team", return_value=ateam
            ),
            patch(
                "ee.hogai.session_summaries.session.summarize_session.get_session_metadata",
                return_value=mock_raw_metadata,
            ),
            patch(
                "ee.hogai.session_summaries.session.summarize_session.get_session_events",
                return_value=(mock_raw_events_columns, []),  # Return columns but no events
            ),
        ):
            with patch(
                "posthog.temporal.ai.session_summary.summarize_session.logger.exception"
            ) as mock_logger_exception:
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
        auser: User,
        ateam: Team,
    ):
        llm_input_data = mock_single_session_summary_llm_inputs(mock_session_id, auser.id)
        compressed_llm_input_data = _compress_redis_data(json.dumps(dataclasses.asdict(llm_input_data)))
        key_base = "stream_llm_test_base"
        input_data = mock_single_session_summary_inputs(mock_session_id, ateam.id, auser.id, key_base)
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
        # Verify summary doesn't exist in DB before the activity
        summary_before = await database_sync_to_async(SingleSessionSummary.objects.get_summary, thread_sensitive=False)(
            team_id=ateam.id,
            session_id=mock_session_id,
            extra_summary_context=input_data.extra_summary_context,
        )
        assert summary_before is None, "Summary should not exist in DB before the activity"
        # First run: generate and store summary
        expected_final_summary = json.dumps(mock_enriched_llm_json_response)
        mock_stream_llm_instance = mock_stream_llm()
        with (
            patch(
                "ee.hogai.session_summaries.llm.consume.stream_llm", return_value=mock_stream_llm_instance
            ) as mock_stream_llm_patch,
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
            # Verify LLM was called
            assert mock_stream_llm_patch.call_count == 1
        # Verify summary was stored in DB after the activity
        summary_after = await database_sync_to_async(SingleSessionSummary.objects.get_summary, thread_sensitive=False)(
            team_id=ateam.id,
            session_id=mock_session_id,
            extra_summary_context=input_data.extra_summary_context,
        )
        assert summary_after is not None, "Summary should exist in DB after the activity"
        assert summary_after.session_id == mock_session_id
        assert summary_after.team_id == ateam.id
        # Reset call counts for second run
        spy_get.reset_mock()
        spy_setex.reset_mock()
        # Second run: should retrieve from DB without calling LLM
        with (
            patch(
                "products.enterprise.backend.hogai.session_summaries.llm.consume.stream_llm"
            ) as mock_stream_llm_patch_2,
            patch("temporalio.activity.heartbeat") as mock_heartbeat_2,
            patch("temporalio.activity.info") as mock_activity_info_2,
        ):
            mock_activity_info_2.return_value.workflow_id = "test_workflow_id_2"
            # Call the activity again - should get from DB
            result_2 = await stream_llm_single_session_summary_activity(input_data)
            # Verify the result matches the stored summary (DB returns summary.summary as dict)
            assert json.loads(result_2) == json.loads(expected_final_summary)
            # Verify LLM was NOT called
            assert mock_stream_llm_patch_2.call_count == 0, "LLM should not be called when summary exists in DB"
            # Verify no Redis operations occurred (DB check happens before Redis)
            assert spy_get.call_count == 0, "Should not get from Redis when summary exists in DB"
            assert spy_setex.call_count == 0, "Should not set to Redis when summary exists in DB"
            # Verify heartbeat was NOT called (no streaming needed)
            assert mock_heartbeat_2.call_count == 0, "Heartbeat should not be called when retrieving from DB"


class TestSummarizeSingleSessionStreamWorkflow:
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
        # Add retry logic for starting test server
        max_retries = 3
        retry_delay = 1
        activity_environment = None
        # Start with retry to avoid flaky `Failed starting test server`
        for attempt in range(max_retries):
            try:
                activity_environment = await WorkflowEnvironment.start_time_skipping()
                break
            except RuntimeError as e:
                if "Failed starting test server" in str(e) and attempt < max_retries - 1:
                    # Wait before retrying to avoid network issues
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                raise
        if activity_environment is None:
            raise RuntimeError("Failed to start test server after multiple attempts")
        try:
            async with Worker(
                activity_environment.client,
                task_queue=settings.MAX_AI_TASK_QUEUE,
                workflows=WORKFLOWS,
                activities=[stream_llm_single_session_summary_activity, fetch_session_data_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ) as worker:
                with (
                    # Mock LLM call
                    patch(
                        "products.enterprise.backend.hogai.session_summaries.llm.consume.stream_llm",
                        return_value=mock_stream_llm(),
                    ),
                    # Mock DB calls
                    patch(
                        "products.enterprise.backend.hogai.session_summaries.session.input_data.get_team",
                        return_value=mock_team,
                    ),
                    patch(
                        "ee.hogai.session_summaries.session.summarize_session.get_session_metadata",
                        return_value=mock_raw_metadata,
                    ),
                    patch(
                        "ee.hogai.session_summaries.session.summarize_session.get_session_events",
                        return_value=(mock_raw_events_columns, mock_raw_events),
                    ),
                    # Mock deterministic hex generation
                    patch.object(
                        SessionSummaryPromptData, "_get_deterministic_hex", side_effect=iter(mock_valid_event_ids)
                    ),
                ):
                    yield activity_environment, worker
        finally:
            # Ensure proper cleanup
            await activity_environment.shutdown()
            await asyncio.sleep(0.1)  # Small delay to ensure cleanup completes

    async def setup_workflow_test(
        self,
        mock_session_id: str,
        mock_single_session_summary_llm_inputs: Callable,
        mock_single_session_summary_inputs: Callable,
        redis_test_setup: AsyncRedisTestContext,
        mock_enriched_llm_json_response: dict[str, Any],
        team_id: int,
        user_id: int,
    ) -> tuple[str, str, SingleSessionSummaryInputs, str, str]:
        # Prepare test data
        session_id = mock_session_id
        llm_input_data = mock_single_session_summary_llm_inputs(session_id, user_id)
        compressed_llm_input_data = _compress_redis_data(json.dumps(dataclasses.asdict(llm_input_data)))
        redis_key_base = f"test_workflow_key_base_{uuid.uuid4()}"
        workflow_id = f"test_workflow_{uuid.uuid4()}"
        # Create workflow input object
        workflow_input = mock_single_session_summary_inputs(session_id, team_id, user_id, redis_key_base)
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

    def test_execute_summarize_session_stream_compression_decompression(
        self,
        mock_enriched_llm_json_response: dict[str, Any],
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_single_session_summary_llm_inputs: Callable,
        sync_redis_test_setup: SyncRedisTestContext,
    ):
        """Test that data is properly compressed before storage and decompressed during streaming."""
        # Prepare input data
        sample_session_summary_data = SingleSessionSummaryData(
            session_id=mock_session_id,
            user_id=mock_user.id,
            prompt_data=True,  # type: ignore
            prompt=True,  # type: ignore
            error_msg=None,
        )
        input_data = mock_single_session_summary_llm_inputs(mock_session_id, mock_user.id)
        # Mock Redis data for streaming updates
        expected_final_summary = json.dumps(mock_enriched_llm_json_response)
        expected_sse_final_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=expected_final_summary
        )
        intermediate_summary = json.dumps({"partial": "data"})
        intermediate_sse_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=intermediate_summary
        )
        # Create compressed Redis data
        intermediate_redis_data = {"last_summary_state": intermediate_summary, "timestamp": 1234567890}
        final_redis_data = {"last_summary_state": expected_final_summary, "timestamp": 1234567891}
        # Compress the data as it would be stored in Redis
        compressed_intermediate_data = _compress_redis_data(json.dumps(intermediate_redis_data))
        compressed_final_data = _compress_redis_data(json.dumps(final_redis_data))
        # Track Redis calls to properly mock responses
        redis_call_count = 0

        def mock_redis_get(key: str) -> bytes | None:
            nonlocal redis_call_count
            # Return compressed data as bytes, as stored in Redis
            if "session_summary" in key:
                current_call_number = redis_call_count
                redis_call_count += 1
                # First call - no data yet
                if current_call_number == 0:
                    return None
                # Second call - stream chunk (compressed)
                elif current_call_number == 1:
                    return compressed_intermediate_data
                # Third call - final data (compressed)
                else:
                    return compressed_final_data
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
                "ee.hogai.session_summaries.session.summarize_session.prepare_data_for_single_session_summary",
                return_value=sample_session_summary_data,
            ),
            patch(
                "ee.hogai.session_summaries.session.summarize_session.prepare_single_session_summary_input",
                return_value=input_data,
            ),
            patch(
                "posthog.temporal.ai.session_summary.summarize_session._start_single_session_summary_workflow_stream",
                return_value=mock_workflow_handle,
            ),
            patch.object(sync_redis_test_setup.redis_client, "get", side_effect=mock_redis_get),
            patch.object(sync_redis_test_setup.redis_client, "setex"),  # Does nothing
            patch.object(sync_redis_test_setup.redis_client, "delete"),  # Does nothing
            # Spy on decompress_redis_data to ensure it's called
            patch(
                "posthog.temporal.ai.session_summary.summarize_session.decompress_redis_data",
                side_effect=decompress_redis_data,
            ) as mock_decompress,
            # Mock time.sleep to speed up test
            patch("posthog.temporal.ai.session_summary.summarize_session.time.sleep"),
        ):
            # Collect results one by one to track the calls
            results = []
            generator = execute_summarize_session_stream(
                session_id=mock_session_id,
                user_id=mock_user.id,
                team=mock_team,
                extra_summary_context=None,
                local_reads_prod=False,
            )
            # Collect all results
            results = list(generator)
            # Decompress should have been called once for the intermediate data only
            # (final data comes from workflow result, not Redis)
            assert mock_decompress.call_count == 1
            assert mock_decompress.call_args_list[0][0][0] == compressed_intermediate_data
            # Verify we got the expected streaming results
            assert len(results) == 2  # intermediate + final
            assert results[0] == intermediate_sse_summary
            assert results[1] == expected_sse_final_summary
            # Verify workflow was polled the expected number of times
            assert mock_workflow_handle.describe.call_count == 3
            assert mock_workflow_handle.result.call_count == 1
            # Verify Redis get was called correctly
            assert redis_call_count == 2  # Once returning None, once returning intermediate data

    def test_execute_summarize_session_stream_decompression_error(
        self,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_single_session_summary_llm_inputs: Callable,
        sync_redis_test_setup: SyncRedisTestContext,
    ):
        """Test that proper error is raised when Redis data cannot be decompressed."""
        # Prepare input data
        sample_session_summary_data = SingleSessionSummaryData(
            session_id=mock_session_id,
            user_id=mock_user.id,
            prompt_data=True,  # type: ignore
            prompt=True,  # type: ignore
            error_msg=None,
        )
        input_data = mock_single_session_summary_llm_inputs(mock_session_id, mock_user.id)
        # Create invalid compressed data (not valid gzip)
        invalid_compressed_data = b"invalid gzip data"

        def mock_redis_get(key: str) -> bytes | None:
            if "session_summary" in key:
                return invalid_compressed_data
            return None

        # Simulate workflow running
        mock_workflow_handle = MagicMock()
        mock_workflow_handle.describe = AsyncMock(return_value=MagicMock(status=WorkflowExecutionStatus.RUNNING))
        with (
            patch(
                "ee.hogai.session_summaries.session.summarize_session.prepare_data_for_single_session_summary",
                return_value=sample_session_summary_data,
            ),
            patch(
                "ee.hogai.session_summaries.session.summarize_session.prepare_single_session_summary_input",
                return_value=input_data,
            ),
            patch(
                "posthog.temporal.ai.session_summary.summarize_session._start_single_session_summary_workflow_stream",
                return_value=mock_workflow_handle,
            ),
            patch.object(sync_redis_test_setup.redis_client, "get", side_effect=mock_redis_get),
            patch.object(sync_redis_test_setup.redis_client, "setex"),
            patch.object(sync_redis_test_setup.redis_client, "delete"),
        ):
            # Execute and expect ValueError due to decompression failure
            with pytest.raises(ValueError) as exc_info:
                list(
                    execute_summarize_session_stream(
                        session_id=mock_session_id,
                        user_id=mock_user.id,
                        team=mock_team,
                        extra_summary_context=None,
                        local_reads_prod=False,
                    )
                )

            # Verify the error message mentions parsing Redis data
            assert "Failed to parse Redis output data" in str(exc_info.value)

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
        input_data = mock_single_session_summary_llm_inputs(mock_session_id, mock_user.id)
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
                "ee.hogai.session_summaries.session.summarize_session.prepare_data_for_single_session_summary",
                return_value=sample_session_summary_data,
            ),
            patch(
                "ee.hogai.session_summaries.session.summarize_session.prepare_single_session_summary_input",
                return_value=input_data,
            ),
            patch(
                "posthog.temporal.ai.session_summary.summarize_session._start_single_session_summary_workflow_stream",
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
        ateam: Team,
        auser: User,
    ):
        """
        Test that the workflow completes successfully and returns the expected result. Also verifies that Redis operations are performed as expected.
        """
        # Set up spies to track Redis and DB operations
        spy_get = mocker.spy(redis_test_setup.redis_client, "get")
        spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")

        _, workflow_id, workflow_input, expected_final_summary, _ = await self.setup_workflow_test(
            mock_session_id,
            mock_single_session_summary_llm_inputs,
            mock_single_session_summary_inputs,
            redis_test_setup,
            mock_enriched_llm_json_response,
            ateam.id,
            auser.id,
        )

        # Mock the DB check to return None (no existing summary)
        with patch("posthog.sync.database_sync_to_async") as mock_sync_to_async:
            mock_sync_to_async.return_value = AsyncMock(return_value=None)

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
                    SummarizeSingleSessionStreamWorkflow.run,
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
        ateam: Team,
        auser: User,
    ):
        """Test that the workflow retries when stream_llm_summary_activity fails initially, but succeeds eventually."""
        _, workflow_id, workflow_input, expected_final_summary, _ = await self.setup_workflow_test(
            mock_session_id,
            mock_single_session_summary_llm_inputs,
            mock_single_session_summary_inputs,
            redis_test_setup,
            mock_enriched_llm_json_response,
            ateam.id,
            auser.id,
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

        # Mock the DB check to return None (no existing summary)
        with patch("posthog.sync.database_sync_to_async") as mock_sync_to_async:
            mock_sync_to_async.return_value = AsyncMock(return_value=None)

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
                        SummarizeSingleSessionStreamWorkflow.run,
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
        ateam: Team,
        auser: User,
    ):
        """Test that the workflow retries when stream_llm_summary_activity and fails, as it exceeds the retries limit."""
        _, workflow_id, workflow_input, _, _ = await self.setup_workflow_test(
            mock_session_id,
            mock_single_session_summary_llm_inputs,
            mock_single_session_summary_inputs,
            redis_test_setup,
            mock_enriched_llm_json_response,
            ateam.id,
            auser.id,
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

        # Mock the DB check to return None (no existing summary)
        with patch("posthog.sync.database_sync_to_async") as mock_sync_to_async:
            mock_sync_to_async.return_value = AsyncMock(return_value=None)

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
                            SummarizeSingleSessionStreamWorkflow.run,
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
        ateam: Team,
        auser: User,
    ):
        """Test that the workflow properly handles incorrect argument types by failing or timing out during argument processing."""
        await self.setup_workflow_test(
            mock_session_id,
            mock_single_session_summary_llm_inputs,
            mock_single_session_summary_inputs,
            redis_test_setup,
            mock_enriched_llm_json_response,
            ateam.id,
            auser.id,
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
                        SummarizeSingleSessionStreamWorkflow.run,
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
