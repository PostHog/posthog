from contextlib import asynccontextmanager, contextmanager
import json
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
from temporalio.worker import Worker, UnsandboxedWorkflowRunner
import pytest
import dataclasses
from pytest_mock import MockerFixture
from ee.hogai.session_summaries.constants import SESSION_SUMMARIES_SYNC_MODEL
from ee.session_recordings.session_summary.prompt_data import SessionSummaryPromptData
from posthog.temporal.ai.session_summary.shared import fetch_session_data_activity
from posthog.temporal.ai.session_summary.state import _compress_redis_data, get_redis_state_client, StateActivitiesEnum

from ee.session_recordings.session_summary.patterns.output_data import (
    EnrichedSessionGroupSummaryPattern,
    EnrichedSessionGroupSummaryPatternStats,
    EnrichedSessionGroupSummaryPatternsList,
    RawSessionGroupSummaryPatternsList,
)
from posthog.temporal.ai.session_summary.state import generate_state_key, store_data_in_redis
from posthog.redis import get_async_client
from posthog.temporal.ai.session_summary.summarize_session_group import (
    SessionGroupSummaryInputs,
    SummarizeSessionGroupWorkflow,
    execute_summarize_session_group,
    get_llm_single_session_summary_activity,
)
from posthog.temporal.ai.session_summary.activities.patterns import (
    assign_events_to_patterns_activity,
    extract_session_group_patterns_activity,
)
from posthog import constants
from collections.abc import AsyncGenerator
from posthog.temporal.tests.ai.conftest import AsyncRedisTestContext
from openai.types.chat.chat_completion import ChatCompletion, Choice, ChatCompletionMessage
from datetime import datetime
from temporalio.testing import WorkflowEnvironment
from posthog.temporal.ai import WORKFLOWS

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
):
    # Prepare input data
    llm_input = mock_single_session_summary_llm_inputs(mock_session_id)
    compressed_llm_input_data = _compress_redis_data(json.dumps(dataclasses.asdict(llm_input)))
    input_data = mock_single_session_summary_inputs(mock_session_id)

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
    # Execute the activity and verify results
    with (
        patch(
            "ee.session_recordings.session_summary.llm.consume.call_llm", new=AsyncMock(return_value=mock_call_llm())
        ),
        patch("temporalio.activity.info") as mock_activity_info,
    ):
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
        # If no exception is raised, the activity completed successfully
        await get_llm_single_session_summary_activity(input_data)
        # Verify Redis operations count
        assert spy_get.call_count == 2  # Get output data (not found) + get input data
        assert spy_setex.call_count == 2  # Initial setup + store generated summary


@pytest.mark.asyncio
async def test_extract_session_group_patterns_activity_standalone(
    mocker: MockerFixture,
    mock_session_id: str,
    mock_enriched_llm_json_response: dict[str, Any],
    mock_single_session_summary_inputs: Callable,
    mock_session_group_summary_of_summaries_inputs: Callable,
    mock_patterns_extraction_yaml_response: str,
    redis_test_setup: AsyncRedisTestContext,
):
    """Test extract_session_group_patterns activity in a standalone mode"""
    # Prepare input data
    session_ids = [f"{mock_session_id}-1", f"{mock_session_id}-2"]
    single_session_inputs = [mock_single_session_summary_inputs(session_id) for session_id in session_ids]
    activity_inputs = mock_session_group_summary_of_summaries_inputs(single_session_inputs)

    # Store session summaries in Redis for each session to be able to get them from inside the activity
    redis_client = get_async_client()
    enriched_summary_str = json.dumps(mock_enriched_llm_json_response)
    for single_session_input in single_session_inputs:
        session_summary_key = generate_state_key(
            key_base=single_session_input.redis_key_base,
            label=StateActivitiesEnum.SESSION_SUMMARY,
            state_id=single_session_input.session_id,
        )
        await store_data_in_redis(redis_client=redis_client, redis_key=session_summary_key, data=enriched_summary_str)
        redis_test_setup.keys_to_cleanup.append(session_summary_key)

    # Set up spies to track Redis operations
    spy_get = mocker.spy(redis_client, "get")
    spy_setex = mocker.spy(redis_client, "setex")

    # Execute the activity
    with (
        patch("ee.session_recordings.session_summary.llm.consume.call_llm") as mock_call_llm,
        patch("temporalio.activity.info") as mock_activity_info,
    ):
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
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
        await extract_session_group_patterns_activity(activity_inputs)
        # Verify LLM was called once to extract patterns
        mock_call_llm.assert_called_once()
        # Try to get result from Redis (cache), fail, then get session summaries to generate result
        assert spy_get.call_count == 1 + len(session_ids)
        # Store extracted patterns, as initial data was stored before we created a spy
        assert spy_setex.call_count == 1


@pytest.mark.asyncio
async def test_assign_events_to_patterns_activity_standalone(
    mocker: MockerFixture,
    mock_session_id: str,
    mock_enriched_llm_json_response: dict[str, Any],
    mock_single_session_summary_inputs: Callable,
    mock_single_session_summary_llm_inputs: Callable,
    mock_session_group_summary_of_summaries_inputs: Callable,
    mock_patterns_assignment_yaml_response: str,
    redis_test_setup: AsyncRedisTestContext,
):
    """Test assign_events_to_patterns_activity standalone"""
    # Prepare input data
    session_ids = [f"{mock_session_id}-1", f"{mock_session_id}-2"]
    single_session_inputs = [mock_single_session_summary_inputs(session_id) for session_id in session_ids]
    activity_input = mock_session_group_summary_of_summaries_inputs(single_session_inputs)
    redis_client = get_async_client()
    enriched_summary_str = json.dumps(mock_enriched_llm_json_response)

    # Store session summaries in Redis for each session to be able to get them from inside the activity
    for single_session_input in single_session_inputs:
        session_summary_key = generate_state_key(
            key_base=single_session_input.redis_key_base,
            label=StateActivitiesEnum.SESSION_SUMMARY,
            state_id=single_session_input.session_id,
        )
        await store_data_in_redis(redis_client=redis_client, redis_key=session_summary_key, data=enriched_summary_str)
        redis_test_setup.keys_to_cleanup.append(session_summary_key)

    # Store single session LLM inputs in Redis to be able to enrich assigned events
    for session_id, single_session_input in zip(session_ids, single_session_inputs):
        llm_input = mock_single_session_summary_llm_inputs(session_id)
        session_db_data_key = generate_state_key(
            key_base=single_session_input.redis_key_base,
            label=StateActivitiesEnum.SESSION_DB_DATA,
            state_id=single_session_input.session_id,
        )
        await store_data_in_redis(
            redis_client=redis_client, redis_key=session_db_data_key, data=json.dumps(dataclasses.asdict(llm_input))
        )
        redis_test_setup.keys_to_cleanup.append(session_db_data_key)

    # Store extracted patterns in Redis to able able to assign events to them
    mock_patterns = RawSessionGroupSummaryPatternsList.model_validate_json(
        '{"patterns": [{"pattern_id": 1, "pattern_name": "Mock Pattern", "pattern_description": "A test pattern", "severity": "medium", "indicators": ["test indicator"]}]}'
    )
    patterns_key = generate_state_key(
        key_base=activity_input.redis_key_base,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id=",".join(session_ids),
    )
    await store_data_in_redis(
        redis_client=redis_client, redis_key=patterns_key, data=mock_patterns.model_dump_json(exclude_none=True)
    )
    redis_test_setup.keys_to_cleanup.append(patterns_key)

    # Set up spies to track Redis operations
    spy_get = mocker.spy(redis_client, "get")

    # Execute the activity
    with (
        patch("ee.session_recordings.session_summary.llm.consume.call_llm") as mock_call_llm,
        patch("temporalio.activity.info") as mock_activity_info,
    ):
        mock_activity_info.return_value.workflow_id = "test_workflow_id"
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
        # Verify Redis operations - gets session summaries, patterns, and session data
        assert spy_get.call_count >= len(session_ids) + 2  # Session summaries + patterns + session data
        # Note: This activity doesn't store in Redis, it returns the result directly


class TestSummarizeSessionGroupWorkflow:
    @contextmanager
    def execute_test_environment(
        self,
        session_ids: list[str],
        mock_call_llm: Callable,
        mock_team: MagicMock,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        mock_valid_event_ids: list[str],
        mock_patterns_extraction_yaml_response: str,
        mock_patterns_assignment_yaml_response: str,
        custom_content: str | None = None,
    ):
        """Test environment for sync Django functions to run the workflow from"""
        # Mock LLM responses
        call_llm_side_effects = (
            [mock_call_llm(custom_content=custom_content) for _ in range(len(session_ids))]  # Single-session summaries
            + [mock_call_llm(custom_content=mock_patterns_extraction_yaml_response)]  # Pattern extraction
            + [mock_call_llm(custom_content=mock_patterns_assignment_yaml_response)]  # Pattern assignment
        )
        with (
            # Mock LLM call
            patch(
                "ee.session_recordings.session_summary.llm.consume.call_llm",
                new=AsyncMock(side_effect=call_llm_side_effects),
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
                SessionSummaryPromptData,
                "_get_deterministic_hex",
                side_effect=iter(mock_valid_event_ids * len(session_ids)),
            ),
        ):
            yield

    @asynccontextmanager
    async def temporal_workflow_test_environment(
        self,
        session_ids: list[str],
        mock_call_llm: Callable,
        mock_team: MagicMock,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        mock_valid_event_ids: list[str],
        mock_patterns_extraction_yaml_response: str,
        mock_patterns_assignment_yaml_response: str,
        custom_content: str | None = None,  # noqa: ARG002
    ) -> AsyncGenerator[tuple[WorkflowEnvironment, Worker], None]:
        """Test environment for Temporal workflow"""
        with self.execute_test_environment(
            session_ids,
            mock_call_llm,
            mock_team,
            mock_raw_metadata,
            mock_raw_events_columns,
            mock_raw_events,
            mock_valid_event_ids,
            mock_patterns_extraction_yaml_response,
            mock_patterns_assignment_yaml_response,
            custom_content=custom_content,
        ):
            async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                async with Worker(
                    activity_environment.client,
                    task_queue=constants.GENERAL_PURPOSE_TASK_QUEUE,
                    workflows=WORKFLOWS,
                    activities=[
                        get_llm_single_session_summary_activity,
                        fetch_session_data_activity,
                        extract_session_group_patterns_activity,
                        assign_events_to_patterns_activity,
                    ],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                ) as worker:
                    yield activity_environment, worker

    def setup_workflow_test(
        self,
        mock_session_id: str,
        mock_session_group_summary_inputs: Callable,
        identifier_suffix: str,
    ) -> tuple[list[str], str, SessionGroupSummaryInputs]:
        # Prepare test data
        session_ids = [
            f"{mock_session_id}-1-{identifier_suffix}",
            f"{mock_session_id}-2-{identifier_suffix}",
        ]
        redis_input_key_base = f"test_group_fetch_{identifier_suffix}_base"
        workflow_input = mock_session_group_summary_inputs(session_ids, redis_input_key_base)
        workflow_id = f"test_workflow_{identifier_suffix}_{uuid.uuid4()}"
        return session_ids, workflow_id, workflow_input

    def test_execute_summarize_session_group(
        self,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_session_group_summary_inputs: Callable,
    ):
        """Test the execute_summarize_session_group starts a Temporal workflow and returns the expected result"""
        session_ids, _, _ = self.setup_workflow_test(mock_session_id, mock_session_group_summary_inputs, "execute")
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
        with patch(
            "posthog.temporal.ai.session_summary.summarize_session_group._execute_workflow",
            new=AsyncMock(return_value=expected_patterns),
        ):
            # Wait for workflow to complete and get result
            result = execute_summarize_session_group(session_ids=session_ids, user_id=mock_user.id, team=mock_team)
            assert result == expected_patterns

    @pytest.mark.asyncio
    async def test_summarize_session_group_workflow(
        self,
        mocker: MockerFixture,
        mock_session_id: str,
        mock_team: MagicMock,
        mock_call_llm: Callable,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        mock_valid_event_ids: list[str],
        mock_session_group_summary_inputs: Callable,
        mock_patterns_extraction_yaml_response: str,
        mock_patterns_assignment_yaml_response: str,
        redis_test_setup: AsyncRedisTestContext,
    ):
        """Test that the workflow completes successfully and returns the expected result"""
        session_ids, workflow_id, workflow_input = self.setup_workflow_test(
            mock_session_id, mock_session_group_summary_inputs, "success"
        )
        # Set up spies to track Redis operations
        spy_get = mocker.spy(redis_test_setup.redis_client, "get")
        spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
        async with self.temporal_workflow_test_environment(
            session_ids,
            mock_call_llm,
            mock_team,
            mock_raw_metadata,
            mock_raw_events_columns,
            mock_raw_events,
            mock_valid_event_ids,
            mock_patterns_extraction_yaml_response,
            mock_patterns_assignment_yaml_response,
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
            # Verify Redis operations count (more operations now due to pattern activities)
            # Operations: session data storage (2) + session summaries (2) + pattern extraction (1)
            assert spy_setex.call_count == 5
            # Operations:
            # - try to get cached DB data (2)
            # - try to get cached single-session summaries (2)
            # - get cached DB data (2)
            # - try to get cached extracted patterns (1)
            # - get cached single-session summaries (2)
            # - try to get cached patterns assignments (1)
            # - get cached extracted patterns (1)
            # - get cached single-session summaries (2)
            # - get cached DB data (2)
            assert spy_get.call_count == 15
