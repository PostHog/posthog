from contextlib import asynccontextmanager, contextmanager
import json
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import importlib
import uuid
from temporalio.worker import Worker, UnsandboxedWorkflowRunner
import pytest
from pytest_mock import MockerFixture
from ee.session_recordings.session_summary.prompt_data import SessionSummaryPromptData
from posthog.temporal.ai.session_summary.shared import (
    compress_llm_input_data,
    fetch_session_data_activity,
)
from posthog.temporal.ai.session_summary.summarize_session_group import (
    SessionGroupSummaryInputs,
    SessionGroupSummaryOfSummariesInputs,
    SummarizeSessionGroupWorkflow,
    execute_summarize_session_group,
    get_llm_session_group_summary_activity,
    get_llm_single_session_summary_activity,
)
from posthog import constants
from collections.abc import AsyncGenerator
from posthog.temporal.tests.ai.conftest import RedisTestContext
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
            model="gpt-4.1-2025-04-14",
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
    mock_enriched_llm_json_response: dict[str, Any],
    mock_single_session_summary_llm_inputs: Callable,
    mock_single_session_summary_inputs: Callable,
    mock_call_llm: Callable,
    redis_test_setup: RedisTestContext,
):
    # Prepare input data
    session_id = "test_single_session_id"
    llm_input = mock_single_session_summary_llm_inputs(session_id)
    compressed_llm_input_data = compress_llm_input_data(llm_input)
    input_data = mock_single_session_summary_inputs(session_id)
    # Set up spies to track Redis operations
    spy_get = mocker.spy(redis_test_setup.redis_client, "get")
    spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
    # Store initial input data
    redis_test_setup.setup_input_data(
        compressed_llm_input_data,
        input_data.redis_input_key,
        input_data.redis_output_key,
    )
    # Execute the activity and verify results
    expected_summary = json.dumps(mock_enriched_llm_json_response)
    with patch(
        "ee.session_recordings.session_summary.llm.consume.call_llm",
        new=AsyncMock(return_value=mock_call_llm()),
    ):
        result = await get_llm_single_session_summary_activity(input_data)
        assert result == expected_summary
        # Verify Redis operations count
        assert spy_get.call_count == 1  # Get input data
        assert spy_setex.call_count == 1  # Inital setup + 0 from the activity


@pytest.mark.asyncio
async def test_get_llm_session_group_summary_activity_standalone(
    mock_user: MagicMock,
    mock_enriched_llm_json_response: dict[str, Any],
    mock_call_llm: Callable,
    mocker: MockerFixture,
):
    # Prepare input data
    session_ids = ["test_single_session_id_1", "test_single_session_id_2"]
    enriched_summary_str = json.dumps(mock_enriched_llm_json_response)
    session_summaries = [enriched_summary_str, enriched_summary_str]
    activity_input = SessionGroupSummaryOfSummariesInputs(
        session_ids=session_ids,
        session_summaries=session_summaries,
        user_id=mock_user.id,
    )
    expected_summary_of_summaries = "everything is good"
    # Spy on the prompt generator to ensure it was called with the correct arguments
    summary_module = importlib.import_module("posthog.temporal.ai.session_summary.summarize_session_group")
    spy_generate_prompt = mocker.spy(summary_module, "generate_session_group_summary_prompt")
    # Execute the activity and verify results
    with patch(
        "ee.session_recordings.session_summary.llm.consume.call_llm",
        new=AsyncMock(return_value=mock_call_llm(custom_content=expected_summary_of_summaries)),
    ):
        result = await get_llm_session_group_summary_activity(activity_input)
        assert result == expected_summary_of_summaries
        spy_generate_prompt.assert_called_once_with(session_summaries, None)


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
        custom_content: str | None = None,
    ):
        """Test environment for sync Django functions to run the workflow from"""
        # Mock LLM responses:
        # Session calls - mock_valid_llm_yaml_response to simulate single-session-summary (YAML)
        # Summary call (last) - summary of summaries (str)
        call_llm_side_effects = [mock_call_llm() for _ in range(len(session_ids))] + [
            mock_call_llm(custom_content=custom_content)
        ]
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
    async def workflow_test_environment(
        self,
        session_ids: list[str],
        mock_call_llm: Callable,
        mock_team: MagicMock,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        mock_valid_event_ids: list[str],
        custom_content: str | None = None,
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
            custom_content=custom_content,
        ):
            async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
                async with Worker(
                    activity_environment.client,
                    task_queue=constants.GENERAL_PURPOSE_TASK_QUEUE,
                    workflows=WORKFLOWS,
                    activities=[
                        get_llm_single_session_summary_activity,
                        get_llm_session_group_summary_activity,
                        fetch_session_data_activity,
                    ],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                ) as worker:
                    yield activity_environment, worker

    def setup_workflow_test(
        self,
        mock_session_group_summary_inputs: Callable,
        identifier_suffix: str,
    ) -> tuple[list[str], str, SessionGroupSummaryInputs, str]:
        # Prepare test data
        session_ids = [
            f"test_workflow_session_id_{identifier_suffix}_1",
            f"test_workflow_session_id_{identifier_suffix}_2",
        ]
        redis_input_key_base = f"test_group_fetch_{identifier_suffix}_base"
        workflow_input = mock_session_group_summary_inputs(session_ids, redis_input_key_base)
        workflow_id = f"test_workflow_{identifier_suffix}_{uuid.uuid4()}"
        expected_summary = "everything is good"
        return session_ids, workflow_id, workflow_input, expected_summary

    def test_execute_summarize_session_group(
        self,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_session_group_summary_inputs: Callable,
    ):
        """Test the execute_summarize_session_group starts a Temporal workflow and returns the expected result"""
        session_ids, _, _, expected_summary = self.setup_workflow_test(mock_session_group_summary_inputs, "execute")
        with patch(
            "posthog.temporal.ai.session_summary.summarize_session_group._execute_workflow",
            new=AsyncMock(return_value=expected_summary),
        ):
            # Wait for workflow to complete and get result
            result = execute_summarize_session_group(session_ids=session_ids, user_id=mock_user.id, team=mock_team)
            assert result == expected_summary

    @pytest.mark.asyncio
    async def test_summarize_session_group_workflow(
        self,
        mocker: MockerFixture,
        mock_team: MagicMock,
        mock_call_llm: Callable,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        mock_valid_event_ids: list[str],
        mock_session_group_summary_inputs: Callable,
        redis_test_setup: RedisTestContext,
    ):
        """Test that the workflow completes successfully and returns the expected result"""
        session_ids, workflow_id, workflow_input, expected_summary = self.setup_workflow_test(
            mock_session_group_summary_inputs, "success"
        )
        # Set up spies to track Redis operations
        spy_get = mocker.spy(redis_test_setup.redis_client, "get")
        spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
        async with self.workflow_test_environment(
            session_ids,
            mock_call_llm,
            mock_team,
            mock_raw_metadata,
            mock_raw_events_columns,
            mock_raw_events,
            mock_valid_event_ids,
            custom_content=expected_summary,
        ) as (activity_environment, worker):
            # Wait for workflow to complete and get result
            result = await activity_environment.client.execute_workflow(
                SummarizeSessionGroupWorkflow.run,
                workflow_input,
                id=workflow_id,
                task_queue=worker.task_queue,
            )
            assert result == expected_summary
            # Verify Redis operations count
            assert spy_setex.call_count == len(session_ids)  # Store DB query data for each session
            assert spy_get.call_count == len(session_ids)  # Get DB query data for each session
