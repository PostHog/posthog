import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai

from ee.hogai.session_summaries import SessionSummaryModelUnavailableError
from ee.hogai.session_summaries.llm.call import call_llm


async def test_call_llm_maps_404_to_model_unavailable_error() -> None:
    # A 404 means the configured model is gone (retired/renamed) — must fail fast, not be retried.
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    not_found = openai.NotFoundError(
        "The model `o3` does not exist", response=httpx.Response(status_code=404, request=request), body=None
    )
    mock_client = MagicMock()
    mock_client.responses.create = AsyncMock(side_effect=not_found)
    with patch("ee.hogai.session_summaries.llm.call.get_async_openai_client", return_value=mock_client):
        with pytest.raises(SessionSummaryModelUnavailableError):
            await call_llm(input_prompt="prompt", session_id="session-1", model="o3", user_id=1)


async def test_call_llm_leaves_other_api_errors_retryable() -> None:
    # A generic transient API error must stay an openai error so callers still treat it as retryable.
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    api_error = openai.APIError(message="boom", request=request, body=None)
    mock_client = MagicMock()
    mock_client.responses.create = AsyncMock(side_effect=api_error)
    with patch("ee.hogai.session_summaries.llm.call.get_async_openai_client", return_value=mock_client):
        with pytest.raises(openai.APIError):
            await call_llm(input_prompt="prompt", session_id="session-1", model="o3", user_id=1)
