import json
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import importlib

import pytest
from pytest_mock import MockerFixture
from posthog.temporal.ai.session_summary.shared import compress_llm_input_data, SingleSessionSummaryInputs
from posthog.temporal.ai.session_summary.summarize_session_group import (
    SessionGroupSummaryOfSummariesInputs,
    get_llm_session_group_summary_activity,
    get_llm_single_session_summary_activity,
)
from posthog.temporal.tests.ai.conftest import RedisTestContext
from openai.types.chat.chat_completion import ChatCompletion, Choice, ChatCompletionMessage
from datetime import datetime


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
    mock_single_session_summary_llm_inputs: Callable[[str], Any],
    mock_single_session_summary_inputs: Callable[[str, str], SingleSessionSummaryInputs],
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
        assert spy_setex.call_count == 1  # Inital setip + 0 from the activity


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
        user_pk=mock_user.pk,
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
