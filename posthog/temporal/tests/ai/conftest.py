from collections.abc import AsyncGenerator, Callable
from typing import Any

import pytest

import pytest_asyncio
from redis import (
    Redis,
    asyncio as aioredis,
)

from posthog.models.user import User
from posthog.redis import TEST_clear_clients, get_async_client, get_client
from posthog.temporal.ai.session_summary.summarize_session_group import SessionGroupSummaryInputs
from posthog.temporal.ai.session_summary.types.group import SessionGroupSummaryOfSummariesInputs
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs

from products.enterprise.backend.hogai.session_summaries.constants import (
    SESSION_SUMMARIES_DB_DATA_REDIS_TTL,
    SESSION_SUMMARIES_STREAMING_MODEL,
    SESSION_SUMMARIES_SYNC_MODEL,
)
from products.enterprise.backend.hogai.session_summaries.session.output_data import SessionSummarySerializer
from products.enterprise.backend.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from products.enterprise.backend.hogai.session_summaries.tests.conftest import *
from products.enterprise.backend.models.session_summaries import (
    ExtraSummaryContext,
    SessionSummaryRunMeta,
    SingleSessionSummary,
)


@pytest.fixture
def mock_single_session_summary_inputs() -> Callable:
    """Factory to produce inputs for single-session-summary related workflows/activities"""

    def _create_inputs(
        session_id: str,
        team_id: int,
        user_id: int,
        redis_key_base: str = "test_key_base",
    ) -> SingleSessionSummaryInputs:
        return SingleSessionSummaryInputs(
            session_id=session_id,
            user_id=user_id,
            team_id=team_id,
            redis_key_base=redis_key_base,
            model_to_use=SESSION_SUMMARIES_STREAMING_MODEL,
        )

    return _create_inputs


@pytest.fixture
def mock_single_session_summary_llm_inputs(
    mock_events_mapping: dict[str, list[Any]],
    mock_event_ids_mapping: dict[str, str],
    mock_events_columns: list[str],
    mock_url_mapping_reversed: dict[str, str],
    mock_window_mapping_reversed: dict[str, str],
) -> Callable:
    """Factory to produce inputs for single-session summarization LLM calls, usually stored in Redis"""

    def _create_inputs(
        session_id: str,
        user_id: int,
    ) -> SingleSessionSummaryLlmInputs:
        return SingleSessionSummaryLlmInputs(
            session_id=session_id,
            user_id=user_id,
            summary_prompt="Generate a summary for this session",
            system_prompt="You are a helpful assistant that summarizes user sessions",
            simplified_events_mapping=mock_events_mapping,
            event_ids_mapping=mock_event_ids_mapping,
            simplified_events_columns=mock_events_columns,
            url_mapping_reversed=mock_url_mapping_reversed,
            window_mapping_reversed=mock_window_mapping_reversed,
            session_start_time_str="2025-03-31T18:40:32.302000Z",
            session_duration=5323,
            model_to_use=SESSION_SUMMARIES_SYNC_MODEL,
        )

    return _create_inputs


@pytest.fixture
def mock_session_group_summary_inputs() -> Callable:
    """Factory to produce inputs for session-group-summary related workflows/activities"""

    def _create_inputs(
        session_ids: list[str],
        team_id: int,
        user_id: int,
        redis_key_base: str = "test_input_base",
    ) -> SessionGroupSummaryInputs:
        return SessionGroupSummaryInputs(
            session_ids=session_ids,
            user_id=user_id,
            team_id=team_id,
            redis_key_base=redis_key_base,
            min_timestamp_str="2025-03-30T00:00:00.000000+00:00",
            max_timestamp_str="2025-04-01T23:59:59.999999+00:00",
            model_to_use=SESSION_SUMMARIES_SYNC_MODEL,
        )

    return _create_inputs


@pytest.fixture
def mock_session_group_summary_of_summaries_inputs() -> Callable:
    """Factory to produce inputs for session-group-summary-of-summaries related activities"""

    def _create_inputs(
        single_session_summaries_inputs: list[SingleSessionSummaryInputs],
        user_id: int,
        team_id: int,
        redis_key_base: str = "test_input_base",
    ) -> SessionGroupSummaryOfSummariesInputs:
        return SessionGroupSummaryOfSummariesInputs(
            single_session_summaries_inputs=single_session_summaries_inputs,
            user_id=user_id,
            team_id=team_id,
            redis_key_base=redis_key_base,
            model_to_use=SESSION_SUMMARIES_SYNC_MODEL,
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
    # All patterns need events assigned to meet the FAILED_PATTERNS_ASSIGNMENT_MIN_RATIO threshold
    return """patterns:
  - pattern_id: 1
    event_ids: ["abcd1234", "defg4567"]
  - pattern_id: 2
    event_ids: ["ghij7890", "mnop3456"]
  - pattern_id: 3
    event_ids: ["stuv9012"]
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


@pytest.fixture
def mock_extra_summary_context() -> ExtraSummaryContext:
    """Create a mock ExtraSummaryContext for testing."""
    return ExtraSummaryContext(focus_area="conversion_funnel")


@pytest.fixture
def mock_session_summary_run_meta() -> SessionSummaryRunMeta:
    """Create a mock SessionSummaryRunMeta for testing."""
    return SessionSummaryRunMeta(
        model_used=SESSION_SUMMARIES_SYNC_MODEL,
        visual_confirmation=True,
    )


@pytest.fixture
def mock_exception_event_ids() -> list[str]:
    """Create a list of mock exception event IDs for testing."""
    return ["mnop3456", "xyz98765"]  # From mock data, mnop3456 has an exception


@pytest.fixture
def mock_session_summary_serializer(
    mock_enriched_llm_json_response: dict[str, Any],
) -> SessionSummarySerializer:
    """Create a valid SessionSummarySerializer instance for testing."""
    serializer = SessionSummarySerializer(data=mock_enriched_llm_json_response)
    if not serializer.is_valid():
        raise ValueError(f"Invalid session summary data: {serializer.errors}")
    return serializer


@pytest.fixture
def mock_intermediate_session_summary_serializer(
    mock_intermediate_llm_json_response: dict[str, Any],
) -> SessionSummarySerializer:
    """Create an intermediate SessionSummarySerializer instance for testing (without UUIDs)."""
    serializer = SessionSummarySerializer(data=mock_intermediate_llm_json_response)
    if not serializer.is_valid():
        raise ValueError(f"Invalid session summary data: {serializer.errors}")
    return serializer


@pytest.fixture
def create_single_session_summary(db) -> Callable:
    """Factory to create SingleSessionSummary instances in the database."""

    def _create_summary(
        team_id: int,
        session_id: str,
        summary: SessionSummarySerializer,
        exception_event_ids: list[str] | None = None,
        extra_summary_context: ExtraSummaryContext | None = None,
        run_metadata: SessionSummaryRunMeta | None = None,
        created_by: User | None = None,
    ) -> None:
        SingleSessionSummary.objects.add_summary(
            team_id=team_id,
            session_id=session_id,
            summary=summary,
            exception_event_ids=exception_event_ids or [],
            extra_summary_context=extra_summary_context,
            run_metadata=run_metadata,
            created_by=created_by,
        )

    return _create_summary


@pytest.fixture
def mock_single_session_summary(
    create_single_session_summary,
    team,
    user,
    mock_session_id: str,
    mock_session_summary_serializer: SessionSummarySerializer,
    mock_exception_event_ids: list[str],
    mock_extra_summary_context: ExtraSummaryContext,
    mock_session_summary_run_meta: SessionSummaryRunMeta,
) -> SingleSessionSummary:
    """Create a single session summary in the database."""
    create_single_session_summary(
        team_id=team.id,
        session_id=mock_session_id,
        summary=mock_session_summary_serializer,
        exception_event_ids=mock_exception_event_ids,
        extra_summary_context=mock_extra_summary_context,
        run_metadata=mock_session_summary_run_meta,
        created_by=user,
    )
    summary = SingleSessionSummary.objects.get_summary(
        team_id=team.id,
        session_id=mock_session_id,
        extra_summary_context=mock_extra_summary_context,
    )
    assert summary is not None, "Summary should exist in DB"
    return summary
