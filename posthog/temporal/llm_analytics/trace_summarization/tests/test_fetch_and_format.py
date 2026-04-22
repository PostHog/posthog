"""Tests for unified fetch_and_format activity."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from posthog.temporal.llm_analytics.trace_summarization.fetch_and_format import (
    _format_generation_text_repr,
    fetch_and_format_activity,
)
from posthog.temporal.llm_analytics.trace_summarization.models import FetchAndFormatInput


@asynccontextmanager
async def _noop_heartbeater(*args, **kwargs):
    yield


class TestFormatGenerationTextRepr:
    @pytest.mark.parametrize(
        "generation_data,expected_fragments",
        [
            pytest.param(
                {
                    "model": "gpt-4",
                    "provider": "openai",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "latency": 1.5,
                    "input": [{"role": "user", "content": "Hello"}],
                    "output": [{"role": "assistant", "content": "Hi there!"}],
                },
                [
                    "Model: gpt-4",
                    "Provider: openai",
                    "input=100",
                    "output=50",
                    "Latency: 1.50s",
                    "[user]: Hello",
                    "[assistant]: Hi there!",
                ],
                id="all_fields",
            ),
            pytest.param(
                {"model": "gpt-4"},
                ["Model: gpt-4"],
                id="minimal_fields",
            ),
            pytest.param(
                {"input": "What is 2+2?", "output": "4"},
                ["What is 2+2?", "4"],
                id="string_input_output",
            ),
        ],
    )
    def test_format_generation(self, generation_data, expected_fragments):
        result = _format_generation_text_repr(generation_data)
        for fragment in expected_fragments:
            assert fragment in result

    def test_minimal_fields_excludes_absent(self):
        result = _format_generation_text_repr({"model": "gpt-4"})
        assert "Provider:" not in result
        assert "Tokens:" not in result


@patch(
    "posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.Heartbeater",
    _noop_heartbeater,
)
class TestFetchAndFormatActivity:
    @pytest.fixture
    def mock_team(self, db):
        from posthog.models.organization import Organization
        from posthog.models.team import Team

        organization = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=organization, name="Test Team")
        return team

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_trace_not_found_returns_skipped(self, mock_team):
        with (
            patch("posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.fetch_trace") as mock_fetch,
        ):
            mock_fetch.return_value = None

            result = await fetch_and_format_activity(
                FetchAndFormatInput(
                    trace_id=str(uuid.uuid4()),
                    trace_first_timestamp=datetime.now(UTC).isoformat(),
                    team_id=mock_team.id,
                    window_start="2025-01-01T00:00:00Z",
                    window_end="2025-01-01T01:00:00Z",
                )
            )

            assert result.skipped is True
            assert result.skip_reason == "trace_not_found"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_generation_not_found_returns_skipped(self, mock_team):
        with patch(
            "posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.execute_hogql_query"
        ) as mock_query:
            mock_query.return_value.results = []

            result = await fetch_and_format_activity(
                FetchAndFormatInput(
                    trace_id=str(uuid.uuid4()),
                    trace_first_timestamp=datetime.now(UTC).isoformat(),
                    team_id=mock_team.id,
                    window_start="2025-01-01T00:00:00Z",
                    window_end="2025-01-01T01:00:00Z",
                    generation_id=str(uuid.uuid4()),
                )
            )

            assert result.skipped is True
            assert result.skip_reason == "generation_not_found"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_trace_success_stores_in_redis(self, mock_team):
        from posthog.schema import LLMTrace, LLMTracePerson

        trace_id = str(uuid.uuid4())

        with (
            patch("posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.fetch_trace") as mock_fetch,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.llm_trace_to_formatter_format"
            ) as mock_to_format,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.format_trace_text_repr"
            ) as mock_format,
            patch("posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.get_async_client"),
            patch("posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.store_text_repr") as mock_store,
        ):
            mock_person = LLMTracePerson(
                uuid=str(uuid.uuid4()), distinct_id="test", created_at=datetime.now(UTC).isoformat(), properties={}
            )
            mock_trace = LLMTrace(
                id=trace_id, createdAt=datetime.now(UTC).isoformat(), distinctId="test", events=[], person=mock_person
            )
            mock_fetch.return_value = mock_trace
            mock_to_format.return_value = ({"id": trace_id}, [{"event": "e1"}, {"event": "e2"}])
            mock_format.return_value = ("L1: text\nL2: more text", False)
            mock_store.return_value = 42

            result = await fetch_and_format_activity(
                FetchAndFormatInput(
                    trace_id=trace_id,
                    trace_first_timestamp=datetime.now(UTC).isoformat(),
                    team_id=mock_team.id,
                    window_start="2025-01-01T00:00:00Z",
                    window_end="2025-01-01T01:00:00Z",
                )
            )

            assert result.skipped is False
            assert result.trace_id == trace_id
            assert result.text_repr_length == len("L1: text\nL2: more text")
            assert result.compressed_size == 42
            assert result.event_count == 2
            assert "trace" in result.redis_key
            mock_store.assert_called_once()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_generation_success_stores_in_redis(self, mock_team):
        trace_id = str(uuid.uuid4())
        generation_id = str(uuid.uuid4())

        with (
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.execute_hogql_query"
            ) as mock_query,
            patch("posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.get_async_client"),
            patch("posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.store_text_repr") as mock_store,
        ):
            mock_query.return_value.results = [("gpt-4", "openai", "input text", "output text", 10, 5, 0.5)]
            mock_store.return_value = 30

            result = await fetch_and_format_activity(
                FetchAndFormatInput(
                    trace_id=trace_id,
                    trace_first_timestamp=datetime.now(UTC).isoformat(),
                    team_id=mock_team.id,
                    window_start="2025-01-01T00:00:00Z",
                    window_end="2025-01-01T01:00:00Z",
                    generation_id=generation_id,
                )
            )

            assert result.skipped is False
            assert result.generation_id == generation_id
            assert result.event_count == 1
            assert result.text_repr_length > 0
            assert "generation" in result.redis_key
            mock_store.assert_called_once()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_oversized_trace_returns_skipped(self, mock_team):
        from posthog.schema import LLMTrace, LLMTraceEvent, LLMTracePerson

        trace_id = str(uuid.uuid4())

        with (
            patch("posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.fetch_trace") as mock_fetch,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.llm_trace_to_formatter_format"
            ) as mock_to_format,
            patch("posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.MAX_RAW_TRACE_SIZE", 10),
        ):
            mock_person = LLMTracePerson(
                uuid=str(uuid.uuid4()), distinct_id="test", created_at=datetime.now(UTC).isoformat(), properties={}
            )
            big_event = LLMTraceEvent(
                id=str(uuid.uuid4()),
                event="$ai_generation",
                createdAt=datetime.now(UTC).isoformat(),
                properties={"data": "x" * 100},
            )
            mock_trace = LLMTrace(
                id=trace_id,
                createdAt=datetime.now(UTC).isoformat(),
                distinctId="test",
                events=[big_event],
                person=mock_person,
            )
            mock_fetch.return_value = mock_trace
            mock_to_format.return_value = ({}, [{"event": "e1"}])

            result = await fetch_and_format_activity(
                FetchAndFormatInput(
                    trace_id=trace_id,
                    trace_first_timestamp=datetime.now(UTC).isoformat(),
                    team_id=mock_team.id,
                    window_start="2025-01-01T00:00:00Z",
                    window_end="2025-01-01T01:00:00Z",
                )
            )

            assert result.skipped is True
            assert result.skip_reason == "trace_too_large"
            assert result.event_count == 1
