from collections.abc import Awaitable, Callable

import pytest
from unittest.mock import AsyncMock, patch

import httpx
import openai
from parameterized import parameterized

from ee.hogai.session_summaries import ExceptionToRetry
from ee.hogai.session_summaries.llm.consume import (
    get_llm_session_group_patterns_assignment,
    get_llm_session_group_patterns_combination,
    get_llm_session_group_patterns_extraction,
)
from ee.hogai.session_summaries.session.summarize_session import PatternsPrompt

_PROMPT = PatternsPrompt(patterns_prompt="find patterns", system_prompt="you are helpful")
_SESSION_IDS = ["00000000-0000-0000-0001-000000000000"]


def _openai_errors() -> list[tuple[str, Exception]]:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(429, request=request)
    return [
        ("api_error", openai.APIError("boom", request=request, body=None)),
        ("timeout", openai.APITimeoutError(request=request)),
        ("rate_limit", openai.RateLimitError("slow down", response=response, body=None)),
    ]


_GROUP_PATTERN_CALLS: dict[str, Callable[[], Awaitable]] = {
    "extraction": lambda: get_llm_session_group_patterns_extraction(
        prompt=_PROMPT, user_id=1, session_ids=_SESSION_IDS, model_to_use="gpt-5.4"
    ),
    "assignment": lambda: get_llm_session_group_patterns_assignment(
        prompt=_PROMPT, user_id=1, session_ids=_SESSION_IDS, model_to_use="gpt-5.4"
    ),
    "combination": lambda: get_llm_session_group_patterns_combination(
        prompt=_PROMPT, user_id=1, session_ids=_SESSION_IDS
    ),
}


class TestGroupPatternsErrorHandling:
    @parameterized.expand(
        [
            (f"{fn_name}_{err_name}", call, error)
            for fn_name, call in _GROUP_PATTERN_CALLS.items()
            for err_name, error in _openai_errors()
        ]
    )
    async def test_openai_errors_reraised_as_exception_to_retry(
        self, _name: str, call: Callable[[], Awaitable], error: Exception
    ) -> None:
        # A transient OpenAI error must surface as ExceptionToRetry so the Temporal
        # activity retries it instead of the raw error blowing up into error tracking.
        with patch("ee.hogai.session_summaries.llm.consume.call_llm", new=AsyncMock(side_effect=error)):
            with pytest.raises(ExceptionToRetry):
                await call()
