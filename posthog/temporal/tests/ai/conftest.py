from collections.abc import Callable, Generator
from ee.session_recordings.session_summary.summarize_session import SingleSessionSummaryLlmInputs
from ee.session_recordings.session_summary.tests.conftest import *
from posthog.temporal.ai.session_summary.shared import SingleSessionSummaryInputs
from unittest.mock import MagicMock
import pytest
from typing import Any
from posthog.redis import get_client
from posthog.temporal.ai.session_summary.summarize_session_group import SessionGroupSummaryInputs
from posthog.temporal.ai.session_summary.shared import SESSION_SUMMARIES_DB_DATA_REDIS_TTL


@pytest.fixture
def mock_single_session_summary_inputs(
    mock_user: MagicMock,
    mock_team: MagicMock,
) -> Callable:
    """Factory to produce inputs for single-session-summary related workflows/activities"""

    def _create_inputs(
        session_id: str, redis_input_key: str = "test_input_key", redis_output_key: str = "test_output_key"
    ) -> SingleSessionSummaryInputs:
        return SingleSessionSummaryInputs(
            session_id=session_id,
            user_id=mock_user.id,
            team_id=mock_team.id,
            redis_input_key=redis_input_key,
            redis_output_key=redis_output_key,
        )

    return _create_inputs


@pytest.fixture
def mock_single_session_summary_llm_inputs(
    mock_user: MagicMock,
    mock_events_mapping: dict[str, list[Any]],
    mock_events_columns: list[str],
    mock_url_mapping_reversed: dict[str, str],
    mock_window_mapping_reversed: dict[str, str],
) -> Callable:
    """Factory to produce inputs for single-session summarization LLM calls, usually stored in Redis"""

    def _create_inputs(session_id: str) -> SingleSessionSummaryLlmInputs:
        return SingleSessionSummaryLlmInputs(
            session_id=session_id,
            user_id=mock_user.id,
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
def mock_session_group_summary_inputs(
    mock_user: MagicMock,
    mock_team: MagicMock,
) -> Callable:
    """Factory to produce inputs for session-group-summary related workflows/activities"""

    def _create_inputs(
        session_ids: list[str], redis_input_key_base: str = "test_input_base"
    ) -> SessionGroupSummaryInputs:
        return SessionGroupSummaryInputs(
            session_ids=session_ids,
            user_id=mock_user.id,
            team_id=mock_team.id,
            redis_input_key_base=redis_input_key_base,
        )

    return _create_inputs


class RedisTestContext:
    def __init__(self):
        self.redis_client = get_client()
        self.keys_to_cleanup = []

    def setup_input_data(self, input_data: bytes, input_key: str, output_key: str | None = None):
        """Set up Redis input data and track keys for cleanup."""
        self.redis_client.setex(
            input_key,
            SESSION_SUMMARIES_DB_DATA_REDIS_TTL,
            input_data,
        )
        keys = [input_key] if not output_key else [input_key, output_key]
        self.keys_to_cleanup.extend(keys)

    def cleanup(self):
        """Clean up all tracked Redis keys."""
        for key in self.keys_to_cleanup:
            self.redis_client.delete(key)


@pytest.fixture
def redis_test_setup() -> Generator[RedisTestContext, None, None]:
    """Context manager for Redis test setup and cleanup."""
    context = RedisTestContext()
    try:
        yield context
    finally:
        context.cleanup()
