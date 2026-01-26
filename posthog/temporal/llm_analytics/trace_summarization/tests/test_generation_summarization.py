"""Tests for generation summarization activity."""

import uuid
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from posthog.temporal.llm_analytics.trace_summarization.generation_summarization import (
    _format_generation_text_repr,
    generate_and_save_generation_summary_activity,
)


class TestFormatGenerationTextRepr:
    """Tests for _format_generation_text_repr helper."""

    def test_format_with_all_fields(self):
        """Test formatting with all fields populated."""
        generation_data = {
            "model": "gpt-4",
            "provider": "openai",
            "input_tokens": 100,
            "output_tokens": 50,
            "latency": 1.5,
            "input": [{"role": "user", "content": "Hello"}],
            "output": [{"role": "assistant", "content": "Hi there!"}],
        }

        result = _format_generation_text_repr(generation_data)

        assert "Model: gpt-4" in result
        assert "Provider: openai" in result
        assert "input=100" in result
        assert "output=50" in result
        assert "Latency: 1.50s" in result
        assert "[user]: Hello" in result
        assert "[assistant]: Hi there!" in result

    def test_format_with_minimal_fields(self):
        """Test formatting with minimal fields."""
        generation_data = {"model": "gpt-4"}

        result = _format_generation_text_repr(generation_data)

        assert "Model: gpt-4" in result
        assert "Provider:" not in result
        assert "Tokens:" not in result

    def test_format_with_string_input_output(self):
        """Test formatting when input/output are strings instead of lists."""
        generation_data = {
            "input": "What is 2+2?",
            "output": "4",
        }

        result = _format_generation_text_repr(generation_data)

        assert "What is 2+2?" in result
        assert "4" in result


class TestGenerateAndSaveGenerationSummaryActivity:
    """Tests for generate_and_save_generation_summary_activity."""

    @pytest.fixture
    def mock_team(self, db):
        """Create a test team."""
        from posthog.models.organization import Organization
        from posthog.models.team import Team

        organization = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=organization, name="Test Team")
        return team

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_generation_not_found_returns_skipped(self, mock_team):
        """Test that missing generation returns skipped result."""
        with patch(
            "posthog.temporal.llm_analytics.trace_summarization.generation_summarization.execute_hogql_query"
        ) as mock_query:
            mock_query.return_value.results = []

            result = await generate_and_save_generation_summary_activity(
                generation_id=str(uuid.uuid4()),
                trace_id=str(uuid.uuid4()),
                trace_first_timestamp=datetime.now(UTC).isoformat(),
                team_id=mock_team.id,
                window_start="2025-01-01T00:00:00Z",
                window_end="2025-01-01T01:00:00Z",
                mode="minimal",
                batch_run_id="test_batch",
                provider="openai",
            )

            assert result.success is False
            assert result.skipped is True
            assert result.skip_reason == "generation_not_found"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_successful_summary_generation(self, mock_team):
        """Test successful summary generation and saving."""
        from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse

        generation_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())

        mock_summary = SummarizationResponse(
            title="Test Generation Summary",
            flow_diagram="A -> B",
            summary_bullets=[],
            interesting_notes=[],
        )

        with (
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.generation_summarization.execute_hogql_query"
            ) as mock_query,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.generation_summarization.summarize"
            ) as mock_summarize,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.generation_summarization.create_event"
            ) as mock_create_event,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.generation_summarization.LLMTracesSummarizerEmbedder"
            ),
        ):
            mock_query.return_value.results = [
                (
                    "gpt-4",
                    "openai",
                    [{"role": "user", "content": "Hi"}],
                    [{"role": "assistant", "content": "Hello"}],
                    10,
                    5,
                    0.5,
                )
            ]
            mock_summarize.return_value = mock_summary

            result = await generate_and_save_generation_summary_activity(
                generation_id=generation_id,
                trace_id=trace_id,
                trace_first_timestamp=datetime.now(UTC).isoformat(),
                team_id=mock_team.id,
                window_start="2025-01-01T00:00:00Z",
                window_end="2025-01-01T01:00:00Z",
                mode="minimal",
                batch_run_id="test_batch",
                provider="openai",
            )

            assert result.success is True
            assert result.trace_id == trace_id
            assert result.generation_id == generation_id
            assert result.text_repr_length > 0

            mock_create_event.assert_called_once()
            call_kwargs = mock_create_event.call_args.kwargs
            assert call_kwargs["properties"]["$ai_generation_id"] == generation_id
            assert call_kwargs["properties"]["$ai_trace_id"] == trace_id

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_embedding_failure_captured(self, mock_team):
        """Test that embedding failures are captured but don't fail the activity."""
        from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse

        mock_summary = SummarizationResponse(
            title="Test",
            flow_diagram="",
            summary_bullets=[],
            interesting_notes=[],
        )

        with (
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.generation_summarization.execute_hogql_query"
            ) as mock_query,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.generation_summarization.summarize"
            ) as mock_summarize,
            patch("posthog.temporal.llm_analytics.trace_summarization.generation_summarization.create_event"),
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.generation_summarization.LLMTracesSummarizerEmbedder"
            ) as mock_embedder_class,
        ):
            mock_query.return_value.results = [("gpt-4", "openai", "input", "output", 10, 5, 0.5)]
            mock_summarize.return_value = mock_summary
            mock_embedder_class.return_value._embed_document.side_effect = Exception("Embedding failed")

            result = await generate_and_save_generation_summary_activity(
                generation_id=str(uuid.uuid4()),
                trace_id=str(uuid.uuid4()),
                trace_first_timestamp=datetime.now(UTC).isoformat(),
                team_id=mock_team.id,
                window_start="2025-01-01T00:00:00Z",
                window_end="2025-01-01T01:00:00Z",
                mode="minimal",
                batch_run_id="test_batch",
                provider="openai",
            )

            assert result.success is True
            assert result.embedding_requested is False
            assert result.embedding_request_error == "Embedding failed"
