from collections.abc import AsyncGenerator, Callable
from ee.hogai.session_summaries.constants import SESSION_SUMMARIES_DB_DATA_REDIS_TTL
from ee.session_recordings.session_summary.summarize_session import SingleSessionSummaryLlmInputs
from ee.session_recordings.session_summary.tests.conftest import *
from posthog.redis import TEST_clear_clients
from unittest.mock import MagicMock
import pytest
import pytest_asyncio
from typing import Any
from posthog.redis import get_async_client, get_client
from redis import asyncio as aioredis
from redis import Redis
from posthog.temporal.ai.session_summary.summarize_session_group import SessionGroupSummaryInputs
from posthog.temporal.ai.session_summary.types.group import SessionGroupSummaryOfSummariesInputs
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs


@pytest.fixture
def mock_single_session_summary_inputs(
    mock_user: MagicMock,
    mock_team: MagicMock,
) -> Callable:
    """Factory to produce inputs for single-session-summary related workflows/activities"""

    def _create_inputs(session_id: str, redis_key_base: str = "test_key_base") -> SingleSessionSummaryInputs:
        return SingleSessionSummaryInputs(
            session_id=session_id,
            user_id=mock_user.id,
            team_id=mock_team.id,
            redis_key_base=redis_key_base,
        )

    return _create_inputs


@pytest.fixture
def mock_single_session_summary_llm_inputs(
    mock_user: MagicMock,
    mock_events_mapping: dict[str, list[Any]],
    mock_event_ids_mapping: dict[str, str],
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
            event_ids_mapping=mock_event_ids_mapping,
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

    def _create_inputs(session_ids: list[str], redis_key_base: str = "test_input_base") -> SessionGroupSummaryInputs:
        return SessionGroupSummaryInputs(
            session_ids=session_ids,
            user_id=mock_user.id,
            team_id=mock_team.id,
            redis_key_base=redis_key_base,
        )

    return _create_inputs


@pytest.fixture
def mock_session_group_summary_of_summaries_inputs(
    mock_user: MagicMock,
) -> Callable:
    """Factory to produce inputs for session-group-summary-of-summaries related activities"""

    def _create_inputs(
        single_session_summaries_inputs: list[SingleSessionSummaryInputs],
        redis_key_base: str = "test_input_base",
    ) -> SessionGroupSummaryOfSummariesInputs:
        return SessionGroupSummaryOfSummariesInputs(
            single_session_summaries_inputs=single_session_summaries_inputs,
            user_id=mock_user.id,
            redis_key_base=redis_key_base,
        )

    return _create_inputs


@pytest.fixture
def mock_patterns_extraction_yaml_response() -> str:
    """Mock YAML response for pattern extraction"""
    return """patterns:
  - pattern_id: 1
    pattern_name: "Mock Pattern"
    pattern_description: "A test pattern"
    severity: "critical"
    indicators: ["test indicator"]
  - pattern_id: 2
    pattern_name: "Another Pattern"
    pattern_description: "Another test pattern"
    severity: "high"
    indicators: ["another indicator"]
  - pattern_id: 3
    pattern_name: "One more pattern"
    pattern_description: "One more pattern test pattern"
    severity: "medium"
    indicators: ["one more indicator"]
"""


@pytest.fixture
def mock_patterns_assignment_yaml_response() -> str:
    """Mock YAML response for pattern assignment"""
    # No pattern 3 assignments and it should be ok, as not all patterns are required to have assigned events
    return """patterns:
  - pattern_id: 1
    event_ids: ["abcd1234", "defg4567"]
  - pattern_id: 2
    event_ids: ["ghij7890", "mnop3456"]
"""


class RedisTestContextBase:
    """Base class for Redis test contexts with shared functionality."""

    def __init__(self):
        # Clear cache to ensure we get the right client type
        TEST_clear_clients()
        self.keys_to_cleanup = []

    def _get_keys_for_cleanup(self, input_key: str, output_key: str | None = None) -> list[str]:
        """Get list of keys to track for cleanup."""
        return [input_key] if not output_key else [input_key, output_key]

    def _clear_clients(self):
        """Clear client cache so subsequent tests get fresh clients."""
        TEST_clear_clients()


class AsyncRedisTestContext(RedisTestContextBase):
    """Async Redis test context for tests using async Redis operations."""

    def __init__(self):
        super().__init__()
        self.redis_client: aioredis.Redis = get_async_client()

    async def setup_input_data(self, input_data: bytes, input_key: str, output_key: str | None = None):
        """Set up Redis input data and track keys for cleanup."""
        await self.redis_client.setex(
            input_key,
            SESSION_SUMMARIES_DB_DATA_REDIS_TTL,
            input_data,
        )
        keys = self._get_keys_for_cleanup(input_key, output_key)
        self.keys_to_cleanup.extend(keys)

    async def cleanup(self):
        """Clean up all tracked Redis keys and clear client cache."""
        for key in self.keys_to_cleanup:
            await self.redis_client.delete(key)
        self._clear_clients()


class SyncRedisTestContext(RedisTestContextBase):
    """Sync Redis test context for tests using sync Redis operations."""

    def __init__(self):
        super().__init__()
        self.redis_client: Redis = get_client()

    def setup_input_data(self, input_data: bytes, input_key: str, output_key: str | None = None):
        """Set up Redis input data and track keys for cleanup."""
        self.redis_client.setex(
            input_key,
            SESSION_SUMMARIES_DB_DATA_REDIS_TTL,
            input_data,
        )
        keys = self._get_keys_for_cleanup(input_key, output_key)
        self.keys_to_cleanup.extend(keys)

    def cleanup(self):
        """Clean up all tracked Redis keys and clear client cache."""
        for key in self.keys_to_cleanup:
            self.redis_client.delete(key)
        self._clear_clients()


@pytest_asyncio.fixture
async def redis_test_setup() -> AsyncGenerator[AsyncRedisTestContext, None]:
    """Async context manager for Redis test setup and cleanup."""
    context = AsyncRedisTestContext()
    try:
        yield context
    finally:
        await context.cleanup()


@pytest.fixture
def sync_redis_test_setup():
    """Sync context manager for Redis test setup and cleanup."""
    context = SyncRedisTestContext()
    try:
        yield context
    finally:
        context.cleanup()
