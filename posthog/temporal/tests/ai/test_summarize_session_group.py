import json
import uuid
import asyncio
import dataclasses
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from openai.types.chat.chat_completion import ChatCompletion, ChatCompletionMessage, Choice
from pytest_mock import MockerFixture
from temporalio.client import WorkflowExecutionStatus
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.models import Team
from posthog.models.user import User
from posthog.redis import get_async_client
from posthog.sync import database_sync_to_async
from posthog.temporal.ai import WORKFLOWS
from posthog.temporal.ai.session_summary.activities.patterns import (
    assign_events_to_patterns_activity,
    combine_patterns_from_chunks_activity,
    extract_session_group_patterns_activity,
    split_session_summaries_into_chunks_for_patterns_extraction_activity,
)
from posthog.temporal.ai.session_summary.state import (
    StateActivitiesEnum,
    _compress_redis_data,
    generate_state_id_from_session_ids,
    generate_state_key,
    get_redis_state_client,
    store_data_in_redis,
)
from posthog.temporal.ai.session_summary.summarize_session_group import (
    SessionGroupSummaryInputs,
    SummarizeSessionGroupWorkflow,
    execute_summarize_session_group,
    fetch_session_batch_events_activity,
    get_llm_single_session_summary_activity,
)
from posthog.temporal.ai.session_summary.types.group import (
    SessionGroupSummaryOfSummariesInputs,
    SessionGroupSummaryPatternsExtractionChunksInputs,
    SessionSummaryStep,
    SessionSummaryStreamUpdate,
)
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.tests.ai.conftest import AsyncRedisTestContext

from ee.hogai.session_summaries.constants import SESSION_SUMMARIES_SYNC_MODEL
from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
from ee.hogai.session_summaries.session.prompt_data import SessionSummaryPromptData
from ee.hogai.session_summaries.session.summarize_session import ExtraSummaryContext
from ee.hogai.session_summaries.session_group.patterns import (
    EnrichedSessionGroupSummaryPattern,
    EnrichedSessionGroupSummaryPatternsList,
    EnrichedSessionGroupSummaryPatternStats,
    RawSessionGroupSummaryPatternsList,
)
from ee.models.session_summaries import SingleSessionSummary

pytestmark = pytest.mark.django_db


@pytest.fixture
def mock_call_llm(mock_valid_llm_yaml_response: str) -> Callable:
    def _mock_call_llm(custom_content: str | None = None) -> ChatCompletion:
        return ChatCompletion(
            id="test_id",
            model=SESSION_SUMMARIES_SYNC_MODEL,
            object="chat.completion",
            created=int(datetime.now().timestamp()),
            choices=[
                Choice(
                    finish_reason="stop",
                    index=0,
                    message=ChatCompletionMessage(
                        content=custom_content or mock_valid_llm_yaml_response, role="assistant"
                    ),
                )
            ],
        )

    return _mock_call_llm


@pytest.mark.asyncio
async def test_get_llm_single_session_summary_activity_standalone(
    mocker: MockerFixture,
    mock_session_id: str,
    mock_single_session_summary_llm_inputs: Callable,
    mock_single_session_summary_inputs: Callable,
    mock_call_llm: Callable,
    redis_test_setup: AsyncRedisTestContext,
    auser: User,
    ateam: Team,
):
    # Prepare input data
    llm_input = mock_single_session_summary_llm_inputs(mock_session_id, auser.id)
    compressed_llm_input_data = _compress_redis_data(json.dumps(dataclasses.asdict(llm_input)))
    input_data = mock_single_session_summary_inputs(mock_session_id, ateam.id, auser.id)
    # Generate Redis keys manually
    _, redis_input_key, redis_output_key = get_redis_state_client(
        key_base=input_data.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_DB_DATA,
        output_label=StateActivitiesEnum.SESSION_SUMMARY,
        state_id=input_data.session_id,
    )
    # Set up spies to track Redis operations
    spy_get = mocker.spy(redis_test_setup.redis_client, "get")
    spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
    # Store initial input data
    assert redis_input_key
    assert redis_output_key
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
    # Execute the activity and verify results
    with (
        patch("ee.hogai.session_summaries.llm.consume.call_llm", new=AsyncMock(return_value=mock_call_llm())),
        patch("temporalio.activity.info") as mock_activity_info,
    ):
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
        # If no exception is raised, the activity completed successfully
        await get_llm_single_session_summary_activity(input_data)
        # Verify Redis operations count
        # The new flow checks DB first, then gets input from Redis, no output storage to Redis
        assert spy_get.call_count == 1  # Get input data from Redis
        assert spy_setex.call_count == 1  # Only initial setup, output goes to the DB
        # Verify summary was stored in DB after the activity
        summary_after = await database_sync_to_async(SingleSessionSummary.objects.get_summary, thread_sensitive=False)(
            team_id=ateam.id,
            session_id=mock_session_id,
            extra_summary_context=input_data.extra_summary_context,
        )
        assert summary_after is not None, "Summary should exist in DB after the activity"
        assert summary_after.session_id == mock_session_id
        assert summary_after.team_id == ateam.id


@pytest.mark.asyncio
async def test_extract_session_group_patterns_activity_standalone(
    mocker: MockerFixture,
    mock_session_id: str,
    mock_intermediate_session_summary_serializer: SessionSummarySerializer,
    mock_single_session_summary_inputs: Callable,
    mock_session_group_summary_of_summaries_inputs: Callable,
    mock_patterns_extraction_yaml_response: str,
    auser: User,
    ateam: Team,
):
    """Test extract_session_group_patterns activity in a standalone mode"""
    # Prepare input data
    session_ids = [f"{mock_session_id}-1", f"{mock_session_id}-2"]
    single_session_inputs = [
        mock_single_session_summary_inputs(session_id, ateam.id, auser.id) for session_id in session_ids
    ]
    activity_inputs = mock_session_group_summary_of_summaries_inputs(single_session_inputs, auser.id, ateam.id)

    # Store session summaries in DB for each session (following the new approach)
    for session_id in session_ids:
        await database_sync_to_async(SingleSessionSummary.objects.add_summary, thread_sensitive=False)(
            team_id=ateam.id,
            session_id=session_id,
            summary=mock_intermediate_session_summary_serializer,
            exception_event_ids=[],
            extra_summary_context=activity_inputs.extra_summary_context,
            created_by=auser,
        )

    # Verify summaries exist in DB before the activity
    summaries_before = await database_sync_to_async(
        SingleSessionSummary.objects.summaries_exist, thread_sensitive=False
    )(
        team_id=ateam.id,
        session_ids=session_ids,
        extra_summary_context=activity_inputs.extra_summary_context,
    )
    for session_id in session_ids:
        assert summaries_before.get(session_id), f"Summary should exist in DB for session {session_id}"

    # Set up spies to track Redis operations
    redis_client = get_async_client()
    spy_get = mocker.spy(redis_client, "get")
    spy_setex = mocker.spy(redis_client, "setex")

    # Execute the activity
    with (
        patch("ee.hogai.session_summaries.llm.consume.call_llm") as mock_call_llm,
        patch("temporalio.activity.info") as mock_activity_info,
        patch("posthog.temporal.ai.session_summary.activities.patterns.async_connect") as mock_async_connect,
    ):
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
        mock_activity_info.return_value.workflow_run_id = "test_run_id"

        # Mock the workflow handle with signal method
        mock_workflow_handle = MagicMock()
        mock_workflow_handle.signal = AsyncMock()
        mock_client = MagicMock()
        mock_client.get_workflow_handle = MagicMock(return_value=mock_workflow_handle)
        mock_async_connect.return_value = mock_client
        # Mock the LLM response with valid YAML patterns
        mock_llm_response = ChatCompletion(
            id="test_id",
            model="test_model",
            object="chat.completion",
            created=int(datetime.now().timestamp()),
            choices=[
                Choice(
                    finish_reason="stop",
                    index=0,
                    message=ChatCompletionMessage(
                        content=mock_patterns_extraction_yaml_response,
                        role="assistant",
                    ),
                )
            ],
        )
        mock_call_llm.return_value = mock_llm_response
        # If no exception is raised, the activity completed successfully
        result = await extract_session_group_patterns_activity(activity_inputs)
        # Verify LLM was called once to extract patterns
        mock_call_llm.assert_called_once()
        # Should return the Redis key where patterns were stored
        assert result is not None and isinstance(result, str)
        # Verify Redis operations:
        # 1 get to check if patterns already cached + 1 setex to store extracted patterns
        assert spy_get.call_count == 1
        assert spy_setex.call_count == 1


@pytest.mark.asyncio
async def test_assign_events_to_patterns_activity_standalone(
    mocker: MockerFixture,
    mock_session_id: str,
    mock_session_summary_serializer: SessionSummarySerializer,
    mock_single_session_summary_inputs: Callable,
    mock_session_group_summary_of_summaries_inputs: Callable,
    mock_patterns_assignment_yaml_response: str,
    redis_test_setup: AsyncRedisTestContext,
    auser: User,
    ateam: Team,
):
    """Test assign_events_to_patterns_activity standalone"""
    # Prepare input data
    session_ids = [f"{mock_session_id}-1", f"{mock_session_id}-2"]
    single_session_inputs = [
        mock_single_session_summary_inputs(session_id, ateam.id, auser.id) for session_id in session_ids
    ]
    activity_input = mock_session_group_summary_of_summaries_inputs(single_session_inputs, auser.id, ateam.id)
    redis_client = get_async_client()

    # Store session summaries in DB for each session (following the new approach)
    for session_id in session_ids:
        await database_sync_to_async(SingleSessionSummary.objects.add_summary, thread_sensitive=False)(
            team_id=ateam.id,
            session_id=session_id,
            summary=mock_session_summary_serializer,
            exception_event_ids=[],
            extra_summary_context=activity_input.extra_summary_context,
            created_by=auser,
        )

    # Verify summaries exist in DB before the activity
    summaries_before = await database_sync_to_async(
        SingleSessionSummary.objects.summaries_exist, thread_sensitive=False
    )(
        team_id=ateam.id,
        session_ids=session_ids,
        extra_summary_context=activity_input.extra_summary_context,
    )
    for session_id in session_ids:
        assert summaries_before.get(session_id), f"Summary should exist in DB for session {session_id}"

    # Store extracted patterns in Redis to be able to assign events to them
    mock_patterns = RawSessionGroupSummaryPatternsList.model_validate_json(
        '{"patterns": [{"pattern_id": 1, "pattern_name": "Mock Pattern", "pattern_description": "A test pattern", "severity": "medium", "indicators": ["test indicator"]}]}'
    )
    patterns_key = generate_state_key(
        key_base=activity_input.redis_key_base,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id=generate_state_id_from_session_ids(session_ids),
    )
    await store_data_in_redis(
        redis_client=redis_client,
        redis_key=patterns_key,
        data=mock_patterns.model_dump_json(exclude_none=True),
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
    )
    redis_test_setup.keys_to_cleanup.append(patterns_key)

    # Set up spies to track Redis operations
    spy_get = mocker.spy(redis_client, "get")
    spy_setex = mocker.spy(redis_client, "setex")

    # Execute the activity
    with (
        patch("ee.hogai.session_summaries.llm.consume.call_llm") as mock_call_llm,
        patch("temporalio.activity.info") as mock_activity_info,
        patch("posthog.temporal.ai.session_summary.activities.patterns.async_connect") as mock_async_connect,
    ):
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
        mock_activity_info.return_value.workflow_run_id = "test_run_id"

        # Mock the workflow handle with signal method
        mock_workflow_handle = MagicMock()
        mock_workflow_handle.signal = AsyncMock()
        mock_client = MagicMock()
        mock_client.get_workflow_handle = MagicMock(return_value=mock_workflow_handle)
        mock_async_connect.return_value = mock_client
        # Mock the LLM response for pattern assignment
        mock_llm_response = ChatCompletion(
            id="test_id",
            model="test_model",
            object="chat.completion",
            created=int(datetime.now().timestamp()),
            choices=[
                Choice(
                    finish_reason="stop",
                    index=0,
                    message=ChatCompletionMessage(
                        content=mock_patterns_assignment_yaml_response,
                        role="assistant",
                    ),
                )
            ],
        )
        mock_call_llm.return_value = mock_llm_response
        result = await assign_events_to_patterns_activity(activity_input)
        # Verify the activity completed successfully
        assert isinstance(result, EnrichedSessionGroupSummaryPatternsList)
        assert len(result.patterns) >= 1  # Should have at least one pattern
        # Verify LLM was called (for pattern assignment)
        mock_call_llm.assert_called()  # May be called multiple times for chunks
        # Verify Redis operations:
        # - 1 get to check if patterns assignments already cached
        # - 1 get to retrieve extracted patterns
        # - 1 setex to store the final patterns with events
        assert spy_get.call_count == 2
        assert spy_setex.call_count == 1


@pytest.mark.asyncio
async def test_assign_events_to_patterns_threshold_check(
    mock_session_id: str,
    mock_session_summary_serializer: SessionSummarySerializer,
    mock_single_session_summary_inputs: Callable,
    mock_session_group_summary_of_summaries_inputs: Callable,
    redis_test_setup: AsyncRedisTestContext,
    auser: User,
    ateam: Team,
):
    """Test that assign_events_to_patterns_activity fails when too few patterns get events assigned"""
    # Prepare input data
    session_ids = [f"{mock_session_id}-1", f"{mock_session_id}-2"]
    single_session_inputs = [
        mock_single_session_summary_inputs(session_id, ateam.id, auser.id) for session_id in session_ids
    ]
    activity_input = mock_session_group_summary_of_summaries_inputs(single_session_inputs, auser.id, ateam.id)
    redis_client = get_async_client()

    # Store session summaries in DB for each session (following the new approach)
    for session_id in session_ids:
        await database_sync_to_async(SingleSessionSummary.objects.add_summary, thread_sensitive=False)(
            team_id=ateam.id,
            session_id=session_id,
            summary=mock_session_summary_serializer,
            exception_event_ids=[],
            extra_summary_context=activity_input.extra_summary_context,
            created_by=auser,
        )

    # Verify summaries exist in DB before testing
    summaries_before = await database_sync_to_async(
        SingleSessionSummary.objects.summaries_exist, thread_sensitive=False
    )(
        team_id=ateam.id,
        session_ids=session_ids,
        extra_summary_context=activity_input.extra_summary_context,
    )
    for session_id in session_ids:
        assert summaries_before.get(session_id), f"Summary should exist in DB for session {session_id}"

    # Store extracted patterns with 4 patterns
    mock_patterns = RawSessionGroupSummaryPatternsList.model_validate_json(
        """{
            "patterns": [
                {"pattern_id": 1, "pattern_name": "Pattern 1", "pattern_description": "Test pattern 1", "severity": "critical", "indicators": ["indicator 1"]},
                {"pattern_id": 2, "pattern_name": "Pattern 2", "pattern_description": "Test pattern 2", "severity": "high", "indicators": ["indicator 2"]},
                {"pattern_id": 3, "pattern_name": "Pattern 3", "pattern_description": "Test pattern 3", "severity": "medium", "indicators": ["indicator 3"]},
                {"pattern_id": 4, "pattern_name": "Pattern 4", "pattern_description": "Test pattern 4", "severity": "low", "indicators": ["indicator 4"]}
            ]
        }"""
    )
    patterns_key = generate_state_key(
        key_base=activity_input.redis_key_base,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id=generate_state_id_from_session_ids(session_ids),
    )
    await store_data_in_redis(
        redis_client=redis_client,
        redis_key=patterns_key,
        data=mock_patterns.model_dump_json(exclude_none=True),
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
    )
    redis_test_setup.keys_to_cleanup.append(patterns_key)

    # Test 1: Should fail when only 2 out of 4 patterns get events (50% < 75% threshold)
    with (
        patch("ee.hogai.session_summaries.llm.consume.call_llm") as mock_call_llm,
        patch("temporalio.activity.info") as mock_activity_info,
        patch("posthog.temporal.ai.session_summary.activities.patterns.async_connect") as mock_async_connect,
    ):
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
        mock_activity_info.return_value.workflow_run_id = "test_run_id"

        # Mock the workflow handle with signal method
        mock_workflow_handle = MagicMock()
        mock_workflow_handle.signal = AsyncMock()
        mock_client = MagicMock()
        mock_client.get_workflow_handle = MagicMock(return_value=mock_workflow_handle)
        mock_async_connect.return_value = mock_client
        # Mock LLM response that only assigns events to 2 patterns
        patterns_assignment_fail = """patterns:
  - pattern_id: 1
    event_ids: ["abcd1234"]
  - pattern_id: 2
    event_ids: ["ghij7890"]
"""
        mock_llm_response = ChatCompletion(
            id="test_id",
            model="test_model",
            object="chat.completion",
            created=int(datetime.now().timestamp()),
            choices=[
                Choice(
                    finish_reason="stop",
                    index=0,
                    message=ChatCompletionMessage(
                        content=patterns_assignment_fail,
                        role="assistant",
                    ),
                )
            ],
        )
        mock_call_llm.return_value = mock_llm_response

        # Should raise ApplicationError due to threshold failure
        with pytest.raises(ApplicationError, match="Too many patterns failed to enrich with session meta"):
            await assign_events_to_patterns_activity(activity_input)

    # Test 2: Should succeed when 3 out of 4 patterns get events (75% == 75% threshold)
    with (
        patch("ee.hogai.session_summaries.llm.consume.call_llm") as mock_call_llm,
        patch("temporalio.activity.info") as mock_activity_info,
        patch("posthog.temporal.ai.session_summary.activities.patterns.async_connect") as mock_async_connect,
    ):
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
        mock_activity_info.return_value.workflow_run_id = "test_run_id"

        # Mock the workflow handle with signal method
        mock_workflow_handle = MagicMock()
        mock_workflow_handle.signal = AsyncMock()
        mock_client = MagicMock()
        mock_client.get_workflow_handle = MagicMock(return_value=mock_workflow_handle)
        mock_async_connect.return_value = mock_client
        # Mock LLM response that assigns events to 3 patterns
        patterns_assignment_success = """patterns:
  - pattern_id: 1
    event_ids: ["abcd1234"]
  - pattern_id: 2
    event_ids: ["ghij7890"]
  - pattern_id: 3
    event_ids: ["mnop3456"]
"""
        mock_llm_response = ChatCompletion(
            id="test_id",
            model="test_model",
            object="chat.completion",
            created=int(datetime.now().timestamp()),
            choices=[
                Choice(
                    finish_reason="stop",
                    index=0,
                    message=ChatCompletionMessage(
                        content=patterns_assignment_success,
                        role="assistant",
                    ),
                )
            ],
        )
        mock_call_llm.return_value = mock_llm_response

        # Should succeed
        result = await assign_events_to_patterns_activity(activity_input)
        assert isinstance(result, EnrichedSessionGroupSummaryPatternsList)
        assert len(result.patterns) == 3  # Should have 3 patterns with events


@pytest.mark.asyncio
async def test_assign_events_to_patterns_filters_non_blocking_exceptions(
    mocker: MockerFixture,
    mock_session_id: str,
    mock_enriched_llm_json_response: dict[str, Any],
    mock_single_session_summary_inputs: Callable,
    mock_session_group_summary_of_summaries_inputs: Callable,
    redis_test_setup: AsyncRedisTestContext,
    auser: User,
    ateam: Team,
):
    """Test that non-blocking exceptions are filtered out from pattern assignments"""
    modified_summary_data = dict(mock_enriched_llm_json_response)
    # Add a non-blocking exception event to the key actions (to skip)
    modified_summary_data["key_actions"][1]["events"].append(
        {
            "description": "Non-blocking error occurred",
            "abandonment": False,
            "confusion": False,
            "exception": "non-blocking",  # This should be filtered out
            "event_id": "xyz98765",
            "timestamp": "2025-03-31T18:41:20.000000+00:00",
            "milliseconds_since_start": 48000,
            "window_id": "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "current_url": "http://localhost:8010/error",
            "event": "$exception",
            "event_type": "error",
            "event_index": 7,
            "session_id": mock_session_id,
            "event_uuid": "00000000-0000-0000-0001-000000000008",
        }
    )
    # Create serializer from modified data
    modified_serializer = SessionSummarySerializer(data=modified_summary_data)
    assert modified_serializer.is_valid(), f"Invalid session summary data: {modified_serializer.errors}"
    # Setup input and store modified session summary in DB
    session_ids = [mock_session_id]
    single_session_inputs = [
        mock_single_session_summary_inputs(session_id, ateam.id, auser.id) for session_id in session_ids
    ]
    activity_input = mock_session_group_summary_of_summaries_inputs(single_session_inputs, auser.id, ateam.id)
    await database_sync_to_async(SingleSessionSummary.objects.add_summary, thread_sensitive=False)(
        team_id=ateam.id,
        session_id=mock_session_id,
        summary=modified_serializer,
        exception_event_ids=[],
        extra_summary_context=activity_input.extra_summary_context,
        created_by=auser,
    )
    # Setup Redis with patterns
    patterns_data = RawSessionGroupSummaryPatternsList(
        patterns=[
            {
                "pattern_id": 1,
                "pattern_name": "Error Pattern",
                "pattern_description": "Pattern for error events",
                "severity": "high",
                "indicators": ["error", "exception"],
            },
            {
                "pattern_id": 2,
                "pattern_name": "Confusion Pattern",
                "pattern_description": "Pattern for user confusion",
                "severity": "medium",
                "indicators": ["confusion", "retry"],
            },
        ]
    )
    _, redis_input_key, _ = get_redis_state_client(
        key_base=activity_input.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id=generate_state_id_from_session_ids(session_ids),
    )
    assert redis_input_key is not None
    await redis_test_setup.setup_input_data(
        _compress_redis_data(patterns_data.model_dump_json()),
        redis_input_key,
    )
    # Create a mock LLM response for pattern assignment
    patterns_assignment_yaml = """patterns:
  - pattern_id: 1
    event_ids: ["mnop3456", "xyz98765"]  # mnop3456 is blocking, xyz98765 is non-blocking
  - pattern_id: 2
    event_ids: ["stuv9012"]  # stuv9012 has abandonment"""
    mock_llm_response = ChatCompletion(
        id="test_id",
        model="test_model",
        object="chat.completion",
        created=int(datetime.now().timestamp()),
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage(
                    content=patterns_assignment_yaml,
                    role="assistant",
                ),
            )
        ],
    )
    # Mock LLM calls and Temporal context
    with (
        patch("ee.hogai.session_summaries.llm.consume.call_llm") as mock_call_llm,
        patch("temporalio.activity.info") as mock_activity_info,
        patch("posthog.temporal.ai.session_summary.activities.patterns.async_connect") as mock_async_connect,
    ):
        # Setup mocks
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
        mock_activity_info.return_value.workflow_run_id = "test_run_id"
        # Mock workflow handle for progress updates
        mock_workflow_handle = AsyncMock()
        mock_workflow_handle.signal = AsyncMock()
        mock_temporal_client = AsyncMock()
        mock_temporal_client.get_workflow_handle = MagicMock(return_value=mock_workflow_handle)
        mock_async_connect.return_value = mock_temporal_client
        # Mock LLM call for pattern assignment
        mock_call_llm.return_value = mock_llm_response
        # Execute activity
        result = await assign_events_to_patterns_activity(activity_input)
    # Assertions
    assert isinstance(result, EnrichedSessionGroupSummaryPatternsList)
    # Pattern 1 should only have mnop3456 (blocking, should be included), not xyz98765 (non-blocking, should be skipped)
    pattern_1 = next((p for p in result.patterns if p.pattern_id == 1), None)
    assert pattern_1 is not None, "Pattern 1 should exist"
    assert len(pattern_1.events) == 1, "Pattern 1 should have only 1 event after filtering"
    assert pattern_1.events[0].target_event.event_id == "mnop3456"
    assert pattern_1.events[0].target_event.exception == "blocking"
    # Pattern 2 should have stuv9012 (abandonment, should be included)
    pattern_2 = next((p for p in result.patterns if p.pattern_id == 2), None)
    assert pattern_2 is not None, "Pattern 2 should exist"
    assert len(pattern_2.events) == 1, "Pattern 2 should have 1 event"
    assert pattern_2.events[0].target_event.event_id == "stuv9012"
    assert pattern_2.events[0].target_event.abandonment is True
    # Verify stats reflect only remaining events
    assert pattern_1.stats.occurences == 1  # Only blocking exception counted
    assert pattern_2.stats.occurences == 1


@pytest.mark.asyncio
async def test_non_blocking_exceptions_dont_fail_enrichment_ratio(
    mocker: MockerFixture,
    mock_session_id: str,
    mock_enriched_llm_json_response: dict[str, Any],
    mock_single_session_summary_inputs: Callable,
    mock_session_group_summary_of_summaries_inputs: Callable,
    redis_test_setup: AsyncRedisTestContext,
    auser: User,
    ateam: Team,
):
    """Test that patterns with only non-blocking exceptions don't count as enrichment failures"""
    # Create a modified session summary with only non-blocking exceptions for some patterns
    modified_summary_data = dict(mock_enriched_llm_json_response)
    # Clear existing events and add specific test events
    modified_summary_data["key_actions"][1]["events"] = [
        {
            "description": "Non-blocking error 1",
            "abandonment": False,
            "confusion": False,
            "exception": "non-blocking",
            "event_id": "nonb0001",
            "timestamp": "2025-03-31T18:41:20.000000+00:00",
            "milliseconds_since_start": 48000,
            "window_id": "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "current_url": "http://localhost:8010/error",
            "event": "$exception",
            "event_type": "error",
            "event_index": 7,
            "session_id": mock_session_id,
            "event_uuid": "00000000-0000-0000-0001-000000000008",
        },
        {
            "description": "Non-blocking error 2",
            "abandonment": False,
            "confusion": False,
            "exception": "non-blocking",
            "event_id": "nonb0002",
            "timestamp": "2025-03-31T18:41:21.000000+00:00",
            "milliseconds_since_start": 49000,
            "window_id": "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "current_url": "http://localhost:8010/error",
            "event": "$exception",
            "event_type": "error",
            "event_index": 8,
            "session_id": mock_session_id,
            "event_uuid": "00000000-0000-0000-0001-000000000009",
        },
        {
            "description": "Blocking error",
            "abandonment": False,
            "confusion": True,
            "exception": "blocking",
            "event_id": "block001",
            "timestamp": "2025-03-31T18:41:22.000000+00:00",
            "milliseconds_since_start": 50000,
            "window_id": "0195ed81-7519-7595-9221-8bb8ddb1fdcc",
            "current_url": "http://localhost:8010/error",
            "event": "$exception",
            "event_type": "error",
            "event_index": 9,
            "session_id": mock_session_id,
            "event_uuid": "00000000-0000-0000-0001-000000000010",
        },
    ]
    # Create serializer from modified data
    modified_serializer = SessionSummarySerializer(data=modified_summary_data)
    assert modified_serializer.is_valid(), f"Invalid session summary data: {modified_serializer.errors}"
    # Setup input
    session_ids = [mock_session_id]
    single_session_inputs = [
        mock_single_session_summary_inputs(session_id, ateam.id, auser.id) for session_id in session_ids
    ]
    activity_input = mock_session_group_summary_of_summaries_inputs(single_session_inputs, auser.id, ateam.id)
    # Store modified session summary in DB
    await database_sync_to_async(SingleSessionSummary.objects.add_summary, thread_sensitive=False)(
        team_id=ateam.id,
        session_id=mock_session_id,
        summary=modified_serializer,
        exception_event_ids=[],
        extra_summary_context=activity_input.extra_summary_context,
        created_by=auser,
    )
    # Setup Redis with 3 patterns
    patterns_data = RawSessionGroupSummaryPatternsList(
        patterns=[
            {
                "pattern_id": 1,
                "pattern_name": "Non-blocking Pattern",
                "pattern_description": "Pattern with only non-blocking exceptions",
                "severity": "low",
                "indicators": ["non-blocking"],
            },
            {
                "pattern_id": 2,
                "pattern_name": "Blocking Pattern",
                "pattern_description": "Pattern with blocking exceptions",
                "severity": "high",
                "indicators": ["blocking"],
            },
            {
                "pattern_id": 3,
                "pattern_name": "Mixed Pattern",
                "pattern_description": "Pattern with both types",
                "severity": "medium",
                "indicators": ["error"],
            },
        ]
    )
    _, redis_input_key, _ = get_redis_state_client(
        key_base=activity_input.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id=generate_state_id_from_session_ids(session_ids),
    )
    assert redis_input_key is not None
    await redis_test_setup.setup_input_data(
        _compress_redis_data(patterns_data.model_dump_json()),
        redis_input_key,
    )
    # Mock LLM response that assigns events to patterns
    patterns_assignment_yaml = """patterns:
  - pattern_id: 1
    event_ids: ["nonb0001", "nonb0002"]  # Only non-blocking
  - pattern_id: 2
    event_ids: ["block001"]  # Only blocking
  - pattern_id: 3
    event_ids: ["nonb0001", "block001"]  # Mixed"""
    mock_llm_response = ChatCompletion(
        id="test_id",
        model="test_model",
        object="chat.completion",
        created=int(datetime.now().timestamp()),
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage(
                    content=patterns_assignment_yaml,
                    role="assistant",
                ),
            )
        ],
    )
    with (
        patch("ee.hogai.session_summaries.llm.consume.call_llm") as mock_call_llm,
        patch("temporalio.activity.info") as mock_activity_info,
        patch("posthog.temporal.ai.session_summary.activities.patterns.async_connect") as mock_async_connect,
    ):
        # Setup mocks
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
        mock_activity_info.return_value.workflow_run_id = "test_run_id"
        # Mock workflow handle for progress updates
        mock_workflow_handle = AsyncMock()
        mock_workflow_handle.signal = AsyncMock()
        mock_temporal_client = AsyncMock()
        mock_temporal_client.get_workflow_handle = MagicMock(return_value=mock_workflow_handle)
        mock_async_connect.return_value = mock_temporal_client
        # Mock LLM call
        mock_call_llm.return_value = mock_llm_response
        # We provide 3 patters, it should fail if less than 75% of the patterns were successful
        # It would return just 2, but one pattern is empty through non-blocking exception removal - so, it should not fail
        result = await assign_events_to_patterns_activity(activity_input)
    # Assertions
    assert isinstance(result, EnrichedSessionGroupSummaryPatternsList)
    # Pattern 1 should be removed (only non-blocking)
    pattern_1 = next((p for p in result.patterns if p.pattern_id == 1), None)
    assert pattern_1 is None, "Pattern 1 with only non-blocking exceptions should be removed"
    # Pattern 2 should exist with blocking exception
    pattern_2 = next((p for p in result.patterns if p.pattern_id == 2), None)
    assert pattern_2 is not None, "Pattern 2 should exist"
    assert len(pattern_2.events) == 1
    assert pattern_2.events[0].target_event.event_id == "block001"
    # Pattern 3 should have only the blocking exception
    pattern_3 = next((p for p in result.patterns if p.pattern_id == 3), None)
    assert pattern_3 is not None, "Pattern 3 should exist"
    assert len(pattern_3.events) == 1, "Pattern 3 should have only blocking event"
    assert pattern_3.events[0].target_event.event_id == "block001"
    # Result should have 2 patterns (patterns 2 and 3)
    assert len(result.patterns) == 2, "Should have 2 patterns with valid events"


class TestSummarizeSessionGroupWorkflow:
    @contextmanager
    def execute_test_environment(
        self,
        session_ids: list[str],
        mock_call_llm: Callable,
        team: Team,
        mock_raw_metadata: dict[str, Any],
        mock_valid_event_ids: list[str],
        mock_patterns_extraction_yaml_response: str,
        mock_patterns_assignment_yaml_response: str,
        mock_cached_session_batch_events_query_response_factory: Callable,
        custom_content: str | None = None,
    ):
        """Test environment for sync Django functions to run the workflow from"""

        class MockMetadataDict(dict):
            """Return the same metadata for all sessions"""

            def __getitem__(self, key: str) -> dict[str, Any]:
                return mock_raw_metadata

            def get(self, key: str, default: Any = None) -> dict[str, Any]:
                return self[key]

        # Mock LLM responses
        call_llm_side_effects = (
            [mock_call_llm(custom_content=custom_content) for _ in range(len(session_ids))]  # Single-session summaries
            + [mock_call_llm(custom_content=mock_patterns_extraction_yaml_response)]  # Pattern extraction
            + [mock_call_llm(custom_content=mock_patterns_assignment_yaml_response)]  # Pattern assignment
        )
        # Mock the workflow handle for progress signals
        mock_workflow_handle = MagicMock()
        mock_workflow_handle.signal = AsyncMock()
        mock_client = MagicMock()
        mock_client.get_workflow_handle = MagicMock(return_value=mock_workflow_handle)

        with (
            # Mock LLM call
            patch(
                "ee.hogai.session_summaries.llm.consume.call_llm",
                new=AsyncMock(side_effect=call_llm_side_effects),
            ),
            # Mock DB calls
            patch("posthog.temporal.ai.session_summary.summarize_session_group.get_team", return_value=team),
            patch(
                "posthog.temporal.ai.session_summary.summarize_session_group.SessionReplayEvents.get_group_metadata",
                return_value=MockMetadataDict(),
            ),
            patch(
                "posthog.temporal.ai.session_summary.summarize_session_group._get_db_events_per_page",
                return_value=mock_cached_session_batch_events_query_response_factory(session_ids),
            ),
            # Mock deterministic hex generation
            patch.object(
                SessionSummaryPromptData,
                "_get_deterministic_hex",
                side_effect=iter(mock_valid_event_ids * len(session_ids)),
            ),
            # Mock async_connect for progress signals in activities
            patch("posthog.temporal.ai.session_summary.activities.patterns.async_connect", return_value=mock_client),
        ):
            yield

    @asynccontextmanager
    async def temporal_workflow_test_environment(
        self,
        session_ids: list[str],
        mock_call_llm: Callable,
        team: Team,
        mock_raw_metadata: dict[str, Any],
        mock_valid_event_ids: list[str],
        mock_patterns_extraction_yaml_response: str,
        mock_patterns_assignment_yaml_response: str,
        mock_cached_session_batch_events_query_response_factory: Callable,
        custom_content: str | None = None,  # noqa: ARG002
    ) -> AsyncGenerator[tuple[WorkflowEnvironment, Worker], None]:
        """Test environment for Temporal workflow"""
        with self.execute_test_environment(
            session_ids,
            mock_call_llm,
            team,
            mock_raw_metadata,
            mock_valid_event_ids,
            mock_patterns_extraction_yaml_response,
            mock_patterns_assignment_yaml_response,
            mock_cached_session_batch_events_query_response_factory,
            custom_content,
        ):
            async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                async with Worker(
                    activity_environment.client,
                    task_queue=constants.GENERAL_PURPOSE_TASK_QUEUE,
                    workflows=WORKFLOWS,
                    activities=[
                        get_llm_single_session_summary_activity,
                        extract_session_group_patterns_activity,
                        assign_events_to_patterns_activity,
                        fetch_session_batch_events_activity,
                        combine_patterns_from_chunks_activity,
                        split_session_summaries_into_chunks_for_patterns_extraction_activity,
                    ],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                ) as worker:
                    yield activity_environment, worker

    def setup_workflow_test(
        self,
        mock_session_id: str,
        mock_session_group_summary_inputs: Callable,
        identifier_suffix: str,
        user_id: int,
        team_id: int,
    ) -> tuple[list[str], str, SessionGroupSummaryInputs]:
        # Prepare test data
        session_ids = [
            f"{mock_session_id}-1-{identifier_suffix}",
            f"{mock_session_id}-2-{identifier_suffix}",
        ]
        redis_input_key_base = f"test_group_fetch_{identifier_suffix}_base"
        workflow_input = mock_session_group_summary_inputs(session_ids, team_id, user_id, redis_input_key_base)
        workflow_id = f"test_workflow_{identifier_suffix}_{uuid.uuid4()}"
        return session_ids, workflow_id, workflow_input

    @pytest.mark.asyncio
    async def test_execute_summarize_session_group(
        self,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_session_group_summary_inputs: Callable,
    ):
        """Test the execute_summarize_session_group starts a Temporal workflow and returns the expected result"""
        session_ids, _, _ = self.setup_workflow_test(
            mock_session_id, mock_session_group_summary_inputs, "execute", mock_user, mock_team
        )
        mock_stats = EnrichedSessionGroupSummaryPatternStats(
            occurences=1,
            sessions_affected=1,
            sessions_affected_ratio=0.5,
            segments_success_ratio=1.0,
        )
        mock_pattern = EnrichedSessionGroupSummaryPattern(
            pattern_id=1,
            pattern_name="Mock Pattern",
            pattern_description="A test pattern",
            severity="low",
            indicators=["test indicator"],
            events=[],
            stats=mock_stats,
        )
        expected_patterns = EnrichedSessionGroupSummaryPatternsList(patterns=[mock_pattern])

        async def mock_workflow_generator():
            """Mock async generator that yields only the final result"""
            yield (SessionSummaryStreamUpdate.FINAL_RESULT, SessionSummaryStep.GENERATING_REPORT, expected_patterns)

        with patch(
            "posthog.temporal.ai.session_summary.summarize_session_group._start_session_group_summary_workflow",
            return_value=mock_workflow_generator(),
        ):
            # Collect all results from the async generator
            results = []
            async for update in execute_summarize_session_group(
                session_ids=session_ids,
                user_id=mock_user.id,
                team=mock_team,
                min_timestamp=datetime.now() - timedelta(days=1),
                max_timestamp=datetime.now(),
            ):
                results.append(update)
            # Verify we got the expected result
            assert len(results) == 1
            assert results[0] == (
                SessionSummaryStreamUpdate.FINAL_RESULT,
                SessionSummaryStep.GENERATING_REPORT,
                expected_patterns,
            )

    @pytest.mark.asyncio
    async def test_summarize_session_group_workflow(
        self,
        mocker: MockerFixture,
        mock_session_id: str,
        auser: User,
        ateam: Team,
        mock_call_llm: Callable,
        mock_raw_metadata: dict[str, Any],
        mock_valid_event_ids: list[str],
        mock_session_group_summary_inputs: Callable,
        mock_patterns_extraction_yaml_response: str,
        mock_patterns_assignment_yaml_response: str,
        mock_cached_session_batch_events_query_response_factory: Callable,
        redis_test_setup: AsyncRedisTestContext,
        mock_session_summary_serializer: SessionSummarySerializer,
    ):
        """Test that the workflow completes successfully and returns the expected result"""
        session_ids, workflow_id, workflow_input = self.setup_workflow_test(
            mock_session_id, mock_session_group_summary_inputs, "success", auser.id, ateam.id
        )

        # Store session summaries in DB for each session (following the new approach)
        for session_id in session_ids:
            await database_sync_to_async(SingleSessionSummary.objects.add_summary, thread_sensitive=False)(
                team_id=ateam.id,
                session_id=session_id,
                summary=mock_session_summary_serializer,
                exception_event_ids=[],
                extra_summary_context=workflow_input.extra_summary_context,
                created_by=auser,
            )

        # Set up spies to track Redis and DB operations
        spy_get = mocker.spy(redis_test_setup.redis_client, "get")
        spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
        spy_db_summaries_exist = mocker.spy(SingleSessionSummary.objects, "summaries_exist")
        spy_db_add_summary = mocker.spy(SingleSessionSummary.objects, "add_summary")
        spy_db_get_bulk_summaries = mocker.spy(SingleSessionSummary.objects, "get_bulk_summaries")
        async with self.temporal_workflow_test_environment(
            session_ids,
            mock_call_llm,
            ateam,
            mock_raw_metadata,
            mock_valid_event_ids,
            mock_patterns_extraction_yaml_response,
            mock_patterns_assignment_yaml_response,
            mock_cached_session_batch_events_query_response_factory,
            custom_content=None,
        ) as (activity_environment, worker):
            # Wait for workflow to complete and get result
            result = await activity_environment.client.execute_workflow(
                SummarizeSessionGroupWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=worker.task_queue,
            )
            # Verify the result is of the correct type
            assert isinstance(result, EnrichedSessionGroupSummaryPatternsList)
            # Verify Redis operations
            # Since summaries are pre-stored in DB, only pattern-related Redis operations occur:
            # setex operations: pattern extraction (1) + pattern assignment (1)
            assert spy_setex.call_count == 2
            # get operations:
            # - check if patterns already cached (1) - extract_session_group_patterns_activity
            # - check if pattern assignments already cached (1) - assign_events_to_patterns_activity
            # - get extracted patterns for assignment (1) - assign_events_to_patterns_activity
            # - get patterns for progress tracking (2) - from workflow status queries
            assert spy_get.call_count == 5
            # Verify DB operations
            # summaries_exist checks:
            # - check which sessions have summaries as batch (1) - fetch_session_batch_events_activity
            # - check for individual sessions (2) - from workflow status queries/debugging
            assert spy_db_summaries_exist.call_count == 3
            # get_bulk_summaries calls:
            # - split into chunks activity (1) via get_ready_summaries_from_db
            # - pattern extraction activity (1 retry, 3 total calls) via get_ready_summaries_from_db
            # - pattern assignment activity (1) via get_ready_summaries_from_db
            assert spy_db_get_bulk_summaries.call_count == 5
            # add_summary calls:
            # - initial test setup added 2 summaries (not counted as they happen before spy setup)
            # - no additional summaries should be added during workflow execution
            assert spy_db_add_summary.call_count == 0

    @pytest.mark.asyncio
    async def test_workflow_progress_tracking(
        self,
        mock_session_id: str,
        auser: User,
        ateam: Team,
        mock_call_llm: Callable,
        mock_raw_metadata: dict[str, Any],
        mock_valid_event_ids: list[str],
        mock_session_group_summary_inputs: Callable,
        mock_patterns_extraction_yaml_response: str,
        mock_patterns_assignment_yaml_response: str,
        mock_cached_session_batch_events_query_response_factory: Callable,
        redis_test_setup: AsyncRedisTestContext,
        mock_session_summary_serializer: SessionSummarySerializer,
    ):
        """Test that workflow progress tracking updates status correctly throughout execution"""
        session_ids, workflow_id, workflow_input = self.setup_workflow_test(
            mock_session_id, mock_session_group_summary_inputs, "progress", auser.id, ateam.id
        )

        # Store session summaries in DB for each session (following the new approach)
        for session_id in session_ids:
            await database_sync_to_async(SingleSessionSummary.objects.add_summary, thread_sensitive=False)(
                team_id=ateam.id,
                session_id=session_id,
                summary=mock_session_summary_serializer,
                exception_event_ids=[],
                extra_summary_context=workflow_input.extra_summary_context,
                created_by=auser,
            )
        # Track status updates during workflow execution
        status_updates: list[tuple[tuple[str, str], int]] = []
        async with self.temporal_workflow_test_environment(
            session_ids,
            mock_call_llm,
            ateam,
            mock_raw_metadata,
            mock_valid_event_ids,
            mock_patterns_extraction_yaml_response,
            mock_patterns_assignment_yaml_response,
            mock_cached_session_batch_events_query_response_factory,
            custom_content=None,
        ) as (activity_environment, worker):
            # Start the workflow
            workflow_handle = await activity_environment.client.start_workflow(
                SummarizeSessionGroupWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=worker.task_queue,
            )
            # Poll for status updates during execution
            max_polls = 20
            poll_count = 0
            workflow_completed = False
            while poll_count < max_polls and not workflow_completed:
                try:
                    # Query current status
                    current_status: tuple[str, str] = await workflow_handle.query("get_current_status")
                    if current_status and current_status not in [s for s, _ in status_updates]:
                        status_updates.append((current_status, poll_count))
                    # Check if workflow is complete
                    describe = await workflow_handle.describe()
                    if describe.status == WorkflowExecutionStatus.COMPLETED:
                        workflow_completed = True
                        break
                    # Short sleep to allow workflow to progress
                    await asyncio.sleep(0.05)
                    poll_count += 1
                except Exception:  # noqa
                    # Workflow might not be ready yet
                    await asyncio.sleep(0.05)
                    poll_count += 1
            # Get the final result
            result = await workflow_handle.result()
            assert isinstance(result, EnrichedSessionGroupSummaryPatternsList)
            # Verify we captured some status updates
            assert len(status_updates) > 0
            # Verify the types of status messages we received
            status_messages = [status[1] for status, _ in status_updates]  # Extract message from (step, message) tuple
            expected_status_patterns = [
                "Fetching session data",
                "Watching sessions",
                "Searching for behavior patterns",
                "Generating a report",
            ]
            # At least one of the expected status patterns should be in the status updates
            found_status_patterns = []
            for status_pattern in expected_status_patterns:
                if any(status_pattern in message for message in status_messages):
                    found_status_patterns.append(status_pattern)
            assert len(found_status_patterns) > 0


@pytest.mark.asyncio
class TestPatternExtractionChunking:
    async def test_empty_input_returns_empty_chunks(self, auser: User, ateam: Team):
        """Test that empty input returns empty list of chunks."""
        inputs = SessionGroupSummaryOfSummariesInputs(
            single_session_summaries_inputs=[],
            user_id=auser.id,
            team_id=ateam.id,
            model_to_use=SESSION_SUMMARIES_SYNC_MODEL,
            extra_summary_context=None,
            redis_key_base="test",
        )

        # Execute the activity directly
        chunks = await split_session_summaries_into_chunks_for_patterns_extraction_activity(inputs)

        assert chunks == []

    async def test_all_sessions_fit_in_single_chunk(
        self,
        auser: User,
        ateam: Team,
        mock_intermediate_session_summary_serializer: SessionSummarySerializer,
        mock_single_session_summary_inputs: Callable,
    ):
        """Test when all sessions fit within token limit in a single chunk."""
        # Setup session IDs
        session_ids = ["session-1", "session-2"]

        # Store session summaries in DB for each session
        for session_id in session_ids:
            await database_sync_to_async(SingleSessionSummary.objects.add_summary, thread_sensitive=False)(
                team_id=ateam.id,
                session_id=session_id,
                summary=mock_intermediate_session_summary_serializer,
                exception_event_ids=[],
                extra_summary_context=ExtraSummaryContext(focus_area="test"),
                created_by=auser,
            )

        # Verify summaries exist in DB before the activity
        summaries_before = await database_sync_to_async(
            SingleSessionSummary.objects.summaries_exist, thread_sensitive=False
        )(
            team_id=ateam.id,
            session_ids=session_ids,
            extra_summary_context=ExtraSummaryContext(focus_area="test"),
        )
        for session_id in session_ids:
            assert summaries_before.get(session_id), f"Summary should exist in DB for session {session_id}"

        # Setup inputs with 2 sessions
        single_session_inputs = [
            mock_single_session_summary_inputs(session_id, ateam.id, auser.id) for session_id in session_ids
        ]

        inputs = SessionGroupSummaryOfSummariesInputs(
            single_session_summaries_inputs=single_session_inputs,
            user_id=auser.id,
            team_id=ateam.id,
            model_to_use=SESSION_SUMMARIES_SYNC_MODEL,
            extra_summary_context=ExtraSummaryContext(focus_area="test"),
            redis_key_base="test",
        )

        # Mock token estimation to ensure all sessions fit in a single chunk
        with patch(
            "posthog.temporal.ai.session_summary.activities.patterns.estimate_tokens_from_strings"
        ) as mock_estimate:
            # Mock token counts: base template=1000, each summary=500
            mock_estimate.side_effect = [1000, 500, 500]  # Total: 2000 < 150000

            chunks = await split_session_summaries_into_chunks_for_patterns_extraction_activity(inputs)

        assert len(chunks) == 1
        assert chunks[0] == ["session-1", "session-2"]

    async def test_sessions_split_into_multiple_chunks(
        self,
        auser: User,
        ateam: Team,
        mock_intermediate_session_summary_serializer: SessionSummarySerializer,
        mock_single_session_summary_inputs: Callable,
    ):
        """Test sessions are split when exceeding token limit."""
        # Setup session IDs
        session_ids = [f"session-{i}" for i in range(3)]

        # Store session summaries in DB for each session
        for session_id in session_ids:
            await database_sync_to_async(SingleSessionSummary.objects.add_summary, thread_sensitive=False)(
                team_id=ateam.id,
                session_id=session_id,
                summary=mock_intermediate_session_summary_serializer,
                exception_event_ids=[],
                extra_summary_context=None,
                created_by=auser,
            )

        # Verify summaries exist in DB before the activity
        summaries_before = await database_sync_to_async(
            SingleSessionSummary.objects.summaries_exist, thread_sensitive=False
        )(
            team_id=ateam.id,
            session_ids=session_ids,
            extra_summary_context=None,
        )
        for session_id in session_ids:
            assert summaries_before.get(session_id), f"Summary should exist in DB for session {session_id}"

        # Setup inputs with 3 sessions
        single_session_inputs = [
            mock_single_session_summary_inputs(session_id, ateam.id, auser.id) for session_id in session_ids
        ]

        inputs = SessionGroupSummaryOfSummariesInputs(
            single_session_summaries_inputs=single_session_inputs,
            user_id=auser.id,
            team_id=ateam.id,
            model_to_use=SESSION_SUMMARIES_SYNC_MODEL,
            extra_summary_context=None,
            redis_key_base="test",
        )

        # Mock token counts: base=1000, session0=80000, session1=70000, session2=500
        # - session0 goes alone (80k + 1k base)
        # - session1 goes into the next chunk (80k + 70k + 1k base > 150k)
        # - session2 fits together with session1 (70k + 500 + 1k base < 150k)
        with patch(
            "posthog.temporal.ai.session_summary.activities.patterns.estimate_tokens_from_strings"
        ) as mock_estimate:
            mock_estimate.side_effect = [1000, 80000, 70000, 500]

            chunks = await split_session_summaries_into_chunks_for_patterns_extraction_activity(inputs)

        assert len(chunks) == 2
        assert chunks[0] == ["session-0"]
        assert chunks[1] == ["session-1", "session-2"]

    async def test_oversized_session_handling(
        self,
        auser: User,
        ateam: Team,
        mock_intermediate_session_summary_serializer: SessionSummarySerializer,
        mock_single_session_summary_inputs: Callable,
    ):
        """Test handling of sessions that exceed token limits."""
        # Setup session IDs
        session_ids = [f"session-{i}" for i in range(4)]

        # Store session summaries in DB for each session
        for session_id in session_ids:
            await database_sync_to_async(SingleSessionSummary.objects.add_summary, thread_sensitive=False)(
                team_id=ateam.id,
                session_id=session_id,
                summary=mock_intermediate_session_summary_serializer,
                exception_event_ids=[],
                extra_summary_context=None,
                created_by=auser,
            )

        # Verify summaries exist in DB before the activity
        summaries_before = await database_sync_to_async(
            SingleSessionSummary.objects.summaries_exist, thread_sensitive=False
        )(
            team_id=ateam.id,
            session_ids=session_ids,
            extra_summary_context=None,
        )
        for session_id in session_ids:
            assert summaries_before.get(session_id), f"Summary should exist in DB for session {session_id}"

        # Setup inputs with 4 sessions
        single_session_inputs = [
            mock_single_session_summary_inputs(session_id, ateam.id, auser.id) for session_id in session_ids
        ]

        inputs = SessionGroupSummaryOfSummariesInputs(
            single_session_summaries_inputs=single_session_inputs,
            user_id=auser.id,
            team_id=ateam.id,
            model_to_use=SESSION_SUMMARIES_SYNC_MODEL,
            extra_summary_context=None,
            redis_key_base="test",
        )

        # Mock token counts and logger:
        # base=1000
        # session-0: 500 (fits normally)
        # session-1: 160000 (exceeds PATTERNS_EXTRACTION_MAX_TOKENS but fits in SINGLE_ENTITY_MAX_TOKENS)
        # session-2: 250000 (exceeds even SINGLE_ENTITY_MAX_TOKENS, should be skipped)
        # session-3: 600 (fits normally)
        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.patterns.estimate_tokens_from_strings"
            ) as mock_estimate,
            patch("posthog.temporal.ai.session_summary.activities.patterns.logger") as mock_logger,
        ):
            mock_estimate.side_effect = [1000, 500, 160000, 250000, 600]

            chunks = await split_session_summaries_into_chunks_for_patterns_extraction_activity(inputs)

        # Expected behavior:
        # - session-0 goes into first chunk
        # - session-1 gets its own chunk (warning logged)
        # - session-2 is skipped (error logged)
        # - session-3 goes into third chunk
        assert len(chunks) == 3
        assert chunks[0] == ["session-0"]
        assert chunks[1] == ["session-1"]
        assert chunks[2] == ["session-3"]

        # Verify logging
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "session-1" in warning_call
        assert "PATTERNS_EXTRACTION_MAX_TOKENS" in warning_call
        assert "SINGLE_ENTITY_MAX_TOKENS" in warning_call

        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args[0][0]
        assert "session-2" in error_call
        assert "SINGLE_ENTITY_MAX_TOKENS" in error_call


@pytest.mark.asyncio
async def test_combine_patterns_from_chunks_activity(
    mocker: MockerFixture,
    mock_session_id: str,
    redis_test_setup: AsyncRedisTestContext,
    auser: User,
    ateam: Team,
):
    """Test combine_patterns_from_chunks_activity."""
    # Prepare test data
    session_ids = [f"{mock_session_id}-1", f"{mock_session_id}-2", f"{mock_session_id}-3"]
    redis_key_base = "test-combine-patterns"
    user_id = auser.id
    # Create chunk patterns to store in Redis
    chunk_patterns_1 = RawSessionGroupSummaryPatternsList(
        patterns=[
            {
                "pattern_id": 1,
                "pattern_name": "Login Flow",
                "pattern_description": "User login pattern",
                "severity": "low",
                "indicators": ["clicked login", "entered credentials"],
            }
        ]
    )
    chunk_patterns_2 = RawSessionGroupSummaryPatternsList(
        patterns=[
            {
                "pattern_id": 2,
                "pattern_name": "Error Pattern",
                "pattern_description": "Multiple errors occurred",
                "severity": "high",
                "indicators": ["error message", "retry attempt"],
            }
        ]
    )
    # Store chunk patterns in Redis
    chunk_key_1 = generate_state_key(
        key_base=redis_key_base,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id="chunk-1",
    )
    chunk_key_2 = generate_state_key(
        key_base=redis_key_base,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id="chunk-2",
    )
    await store_data_in_redis(
        redis_client=redis_test_setup.redis_client,
        redis_key=chunk_key_1,
        data=chunk_patterns_1.model_dump_json(exclude_none=True),
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
    )
    await store_data_in_redis(
        redis_client=redis_test_setup.redis_client,
        redis_key=chunk_key_2,
        data=chunk_patterns_2.model_dump_json(exclude_none=True),
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
    )
    redis_test_setup.keys_to_cleanup.extend([chunk_key_1, chunk_key_2])
    # Set up spies
    spy_get = mocker.spy(redis_test_setup.redis_client, "get")
    spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
    # Mock the LLM combination function
    with (
        patch(
            "posthog.temporal.ai.session_summary.activities.patterns.get_llm_session_group_patterns_combination"
        ) as mock_combine,
        patch("temporalio.activity.info") as mock_activity_info,
    ):
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
        # Mock returns combined patterns
        combined_patterns = RawSessionGroupSummaryPatternsList(
            patterns=[
                {
                    "pattern_id": 1,
                    "pattern_name": "Login Flow",
                    "pattern_description": "User login pattern",
                    "severity": "low",
                    "indicators": ["clicked login", "entered credentials"],
                },
                {
                    "pattern_id": 2,
                    "pattern_name": "Error Pattern",
                    "pattern_description": "Multiple errors occurred",
                    "severity": "high",
                    "indicators": ["error message", "retry attempt"],
                },
            ]
        )
        mock_combine.return_value = combined_patterns
        # Execute the activity
        inputs = SessionGroupSummaryPatternsExtractionChunksInputs(
            redis_keys_of_chunks_to_combine=[chunk_key_1, chunk_key_2],
            redis_key_base=redis_key_base,
            session_ids=session_ids,
            user_id=user_id,
            team_id=ateam.id,
            extra_summary_context=None,
        )
        await combine_patterns_from_chunks_activity(inputs)
        # Verify Redis operations
        # 1 get for checking if combined patterns exist + 2 gets for chunk patterns
        assert spy_get.call_count == 3
        # 1 setex for storing combined patterns (2 initial setex were before spy)
        assert spy_setex.call_count == 1
        # Verify LLM was called
        mock_combine.assert_called_once()


@pytest.mark.asyncio
async def test_run_patterns_extraction_with_chunking_and_redis_keys(
    mock_session_id: str,
    redis_test_setup: AsyncRedisTestContext,
    auser: User,
    ateam: Team,
    mock_session_group_summary_of_summaries_inputs: Callable,
):
    """Verify correct Redis key generation and chunks combination when chunking."""
    # Create test data for 4 sessions that will be split into 2 chunks
    session_ids = [f"{mock_session_id}-{i}" for i in range(1, 5)]
    chunk1_sessions = session_ids[:2]
    chunk2_sessions = session_ids[2:]
    redis_key_base = "test-patterns-extraction"
    # Create single session summary inputs for each session
    single_session_inputs = [
        SingleSessionSummaryInputs(
            session_id=session_id,
            user_id=auser.id,
            team_id=ateam.id,
            redis_key_base=redis_key_base,
            model_to_use=SESSION_SUMMARIES_SYNC_MODEL,
        )
        for session_id in session_ids
    ]
    # Create activity inputs
    inputs = mock_session_group_summary_of_summaries_inputs(
        single_session_summaries_inputs=single_session_inputs,
        team_id=ateam.id,
        user_id=auser.id,
        redis_key_base=redis_key_base,
    )
    # Apply mocks and run the activity
    with (
        patch(
            "posthog.temporal.ai.session_summary.summarize_session_group.split_session_summaries_into_chunks_for_patterns_extraction_activity",
            new_callable=AsyncMock,
        ) as mock_split,
        patch(
            "posthog.temporal.ai.session_summary.summarize_session_group.extract_session_group_patterns_activity",
            new_callable=AsyncMock,
        ) as mock_extract,
        patch(
            "posthog.temporal.ai.session_summary.activities.patterns.get_llm_session_group_patterns_combination",
            new_callable=AsyncMock,
        ) as mock_llm_combine,
        patch("temporalio.workflow.execute_activity") as mock_execute_activity,
        patch("temporalio.activity.info") as mock_activity_info,
    ):
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
        # Mock split_session_summaries_into_chunks to return 2 chunks
        mock_split.return_value = [chunk1_sessions, chunk2_sessions]
        # Generate the Redis keys using hashed state_ids
        chunk1_state_id = generate_state_id_from_session_ids(chunk1_sessions)
        chunk2_state_id = generate_state_id_from_session_ids(chunk2_sessions)
        chunk1_redis_key = generate_state_key(
            key_base=redis_key_base,
            label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
            state_id=chunk1_state_id,
        )
        chunk2_redis_key = generate_state_key(
            key_base=redis_key_base,
            label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
            state_id=chunk2_state_id,
        )
        # Store patterns in Redis for each chunk (simulating what extract_session_group_patterns_activity would do)
        chunk1_patterns = RawSessionGroupSummaryPatternsList(
            patterns=[
                {
                    "pattern_id": 1,
                    "pattern_name": "Pattern from chunk 1",
                    "pattern_description": "Test pattern 1",
                    "severity": "low",
                    "indicators": ["indicator1"],
                }
            ]
        )
        chunk2_patterns = RawSessionGroupSummaryPatternsList(
            patterns=[
                {
                    "pattern_id": 2,
                    "pattern_name": "Pattern from chunk 2",
                    "pattern_description": "Test pattern 2",
                    "severity": "high",
                    "indicators": ["indicator2"],
                }
            ]
        )
        await store_data_in_redis(
            redis_client=redis_test_setup.redis_client,
            redis_key=chunk1_redis_key,
            data=chunk1_patterns.model_dump_json(),
            label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        )
        await store_data_in_redis(
            redis_client=redis_test_setup.redis_client,
            redis_key=chunk2_redis_key,
            data=chunk2_patterns.model_dump_json(),
            label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        )

        async def execute_activity_router(activity, inputs, *args, **kwargs):
            # Route based on the inputs type and activity properties
            if isinstance(inputs, SessionGroupSummaryOfSummariesInputs):
                # Check if this is for chunking or extraction
                if "split" in str(activity):
                    return await mock_split(inputs, *args, **kwargs)
                elif "extract" in str(activity):
                    return await mock_extract(inputs, *args, **kwargs)
            elif isinstance(inputs, SessionGroupSummaryPatternsExtractionChunksInputs):
                # This is the combine activity - run the real one (without workflow-specific kwargs)
                return await combine_patterns_from_chunks_activity(inputs)

        # Setup mock_execute_activity to route to the correct mock or real activity
        mock_execute_activity.side_effect = execute_activity_router
        # Mock extract_session_group_patterns_activity to return the correct Redis keys
        mock_extract.side_effect = [chunk1_redis_key, chunk2_redis_key]
        # Mock LLM combination to return combined patterns
        mock_llm_combine.return_value = RawSessionGroupSummaryPatternsList(
            patterns=chunk1_patterns.patterns + chunk2_patterns.patterns
        )
        # Create workflow instance and run patterns extraction
        workflow = SummarizeSessionGroupWorkflow()
        result = await workflow._run_patterns_extraction(inputs)
        # Verify the result
        assert result == session_ids  # All sessions should have patterns extracted
        mock_split.assert_called_once()  # The chunking was done
        assert mock_extract.call_count == 2  # Extract was called once per chunk
        mock_llm_combine.assert_called_once()  # LLM combination was called
        # Combined patterns were stored in Redis properly
        combined_key = generate_state_key(
            key_base=redis_key_base,
            label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
            state_id=generate_state_id_from_session_ids(session_ids),
        )
        stored_data = await redis_test_setup.redis_client.get(combined_key)
        assert stored_data is not None
        redis_test_setup.keys_to_cleanup.append(combined_key)


@pytest.mark.asyncio
async def test_combine_patterns_from_chunks_activity_fails_with_missing_chunks(
    mock_session_id: str,
    redis_test_setup: AsyncRedisTestContext,
    auser: User,
    ateam: Team,
):
    """Test that combine_patterns_from_chunks_activity fails when any chunk is missing."""
    # Prepare test data
    session_ids = [f"{mock_session_id}-1", f"{mock_session_id}-2"]
    redis_key_base = "test-combine-patterns-missing"
    user_id = auser.id
    # Create only one chunk pattern (simulating missing chunk)
    chunk_patterns_1 = RawSessionGroupSummaryPatternsList(
        patterns=[
            {
                "pattern_id": 1,
                "pattern_name": "Test Pattern",
                "pattern_description": "Test",
                "severity": "low",
                "indicators": ["test"],
            }
        ]
    )
    chunk_key_1 = generate_state_key(
        key_base=redis_key_base,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id="chunk-1",
    )
    chunk_key_2 = generate_state_key(
        key_base=redis_key_base,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id="chunk-2-missing",  # This one won't exist in Redis
    )
    # Store only the first chunk
    await store_data_in_redis(
        redis_client=redis_test_setup.redis_client,
        redis_key=chunk_key_1,
        data=chunk_patterns_1.model_dump_json(exclude_none=True),
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
    )
    redis_test_setup.keys_to_cleanup.append(chunk_key_1)

    with patch("temporalio.activity.info") as mock_activity_info:
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
        # Should raise ValueError when a chunk is missing
        with pytest.raises(ValueError):
            inputs = SessionGroupSummaryPatternsExtractionChunksInputs(
                redis_keys_of_chunks_to_combine=[chunk_key_1, chunk_key_2],
                redis_key_base=redis_key_base,
                session_ids=session_ids,
                user_id=user_id,
                team_id=ateam.id,
                extra_summary_context=None,
            )
            await combine_patterns_from_chunks_activity(inputs)


@pytest.mark.asyncio
async def test_combine_patterns_from_chunks_activity_fails_when_no_chunks(
    mock_session_id: str,
    redis_test_setup: AsyncRedisTestContext,
    auser: User,
    ateam: Team,
):
    """Test that activity fails when no chunks can be retrieved."""
    # Prepare test data with non-existent chunk keys
    session_ids = [f"{mock_session_id}-1", f"{mock_session_id}-2"]
    redis_key_base = "test-combine-patterns-fail"
    user_id = auser.id
    chunk_key_1 = generate_state_key(
        key_base=redis_key_base,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id="non-existent-1",
    )
    chunk_key_2 = generate_state_key(
        key_base=redis_key_base,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id="non-existent-2",
    )

    with patch("temporalio.activity.info") as mock_activity_info:
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
        # Should raise ValueError when chunks are missing
        with pytest.raises(ValueError):
            inputs = SessionGroupSummaryPatternsExtractionChunksInputs(
                redis_keys_of_chunks_to_combine=[chunk_key_1, chunk_key_2],
                redis_key_base=redis_key_base,
                session_ids=session_ids,
                user_id=user_id,
                team_id=ateam.id,
                extra_summary_context=None,
            )
            await combine_patterns_from_chunks_activity(inputs)
