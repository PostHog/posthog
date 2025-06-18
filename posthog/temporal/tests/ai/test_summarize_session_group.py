import json
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_mock import MockerFixture
from posthog.temporal.ai.session_summary.shared import compress_llm_input_data, SingleSessionSummaryInputs
from posthog.temporal.ai.session_summary.summarize_session_group import (
    get_llm_single_session_summary_activity,
)
from posthog.temporal.tests.ai.conftest import RedisTestContext
from openai.types.chat.chat_completion import ChatCompletion, Choice, ChatCompletionMessage
from datetime import datetime


@pytest.fixture
def mock_call_llm(mock_valid_llm_yaml_response: str) -> ChatCompletion:
    return ChatCompletion(
        id="test_id",
        model="gpt-4.1-2025-04-14",
        object="chat.completion",
        created=int(datetime.now().timestamp()),
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage(content=mock_valid_llm_yaml_response, role="assistant"),
            )
        ],
    )


@pytest.mark.asyncio
async def test_get_llm_single_session_summary_activity_standalone(
    mocker: MockerFixture,
    mock_enriched_llm_json_response: dict[str, Any],
    mock_single_session_summary_llm_inputs: Callable[[str], Any],
    mock_single_session_summary_inputs: Callable[[str, str], SingleSessionSummaryInputs],
    mock_call_llm: ChatCompletion,
    redis_test_setup: RedisTestContext,
):
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
    # Run the activity and verify results
    expected_summary = json.dumps(mock_enriched_llm_json_response)
    with patch(
        "ee.session_recordings.session_summary.llm.consume.call_llm",
        new=AsyncMock(return_value=mock_call_llm),
    ):
        result = await get_llm_single_session_summary_activity(input_data)
        assert result == expected_summary
        # Verify Redis operations count
        assert spy_get.call_count == 1  # Get input data
        assert spy_setex.call_count == 1  # Inital setip + 0 from the activity
