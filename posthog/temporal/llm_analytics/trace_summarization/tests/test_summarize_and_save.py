"""Tests for unified summarize_and_save activity."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from posthog.temporal.llm_analytics.trace_summarization.models import SummarizeAndSaveInput, TextReprExpiredError
from posthog.temporal.llm_analytics.trace_summarization.summarize_and_save import summarize_and_save_activity


@asynccontextmanager
async def _noop_heartbeater(*args, **kwargs):
    yield


@pytest.fixture
def mock_team(db):
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    organization = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=organization, name="Test Team")
    return team


def _make_mock_summary():
    from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse

    return SummarizationResponse(
        title="Test Summary",
        flow_diagram="A -> B",
        summary_bullets=[],
        interesting_notes=[],
    )


def _make_input(mock_team, generation_id=None):
    return SummarizeAndSaveInput(
        redis_key="llma:summarization:trace:1:abc:text_repr",
        trace_id=str(uuid.uuid4()),
        team_id=mock_team.id,
        trace_first_timestamp=datetime.now(UTC).isoformat(),
        mode="minimal",
        batch_run_id="test_batch",
        model="gpt-4.1-nano",
        generation_id=generation_id,
        event_count=3,
        text_repr_length=100,
    )


@patch(
    "posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.Heartbeater",
    _noop_heartbeater,
)
class TestSummarizeAndSaveActivity:
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_redis_key_missing_raises_text_repr_expired(self, mock_team):
        with (
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.get_async_client"),
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.load_text_repr") as mock_load,
        ):
            mock_load.return_value = None

            with pytest.raises(TextReprExpiredError):
                await summarize_and_save_activity(_make_input(mock_team))

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_trace_summary_success(self, mock_team):
        mock_summary = _make_mock_summary()
        input_data = _make_input(mock_team)

        with (
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.get_async_client"),
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.load_text_repr") as mock_load,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.delete_text_repr"
            ) as mock_delete,
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.summarize") as mock_summarize,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.create_event"
            ) as mock_create_event,
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.LLMTracesSummarizerEmbedder"),
        ):
            mock_load.return_value = "text_repr content"
            mock_summarize.return_value = mock_summary

            result = await summarize_and_save_activity(input_data)

            assert result.success is True
            assert result.trace_id == input_data.trace_id
            assert result.generation_id is None
            assert result.embedding_requested is True
            mock_create_event.assert_called_once()
            call_kwargs = mock_create_event.call_args.kwargs
            assert call_kwargs["event"] == "$ai_trace_summary"
            assert call_kwargs["properties"]["$ai_trace_id"] == input_data.trace_id
            mock_delete.assert_called_once()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_generation_summary_success(self, mock_team):
        mock_summary = _make_mock_summary()
        generation_id = str(uuid.uuid4())
        input_data = _make_input(mock_team, generation_id=generation_id)

        with (
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.get_async_client"),
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.load_text_repr") as mock_load,
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.delete_text_repr"),
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.summarize") as mock_summarize,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.create_event"
            ) as mock_create_event,
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.LLMTracesSummarizerEmbedder"),
        ):
            mock_load.return_value = "generation text repr"
            mock_summarize.return_value = mock_summary

            result = await summarize_and_save_activity(input_data)

            assert result.success is True
            assert result.generation_id == generation_id
            assert result.embedding_requested is True
            call_kwargs = mock_create_event.call_args.kwargs
            assert call_kwargs["event"] == "$ai_generation_summary"
            assert call_kwargs["properties"]["$ai_generation_id"] == generation_id

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_embedding_failure_captured_not_fatal(self, mock_team):
        mock_summary = _make_mock_summary()
        input_data = _make_input(mock_team)

        with (
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.get_async_client"),
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.load_text_repr") as mock_load,
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.delete_text_repr"),
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.summarize") as mock_summarize,
            patch("posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.create_event"),
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarize_and_save.LLMTracesSummarizerEmbedder"
            ) as mock_embedder_class,
        ):
            mock_load.return_value = "text repr"
            mock_summarize.return_value = mock_summary
            mock_embedder_class.return_value._embed_document.side_effect = Exception("Kafka down")

            result = await summarize_and_save_activity(input_data)

            assert result.success is True
            assert result.embedding_requested is False
            assert result.embedding_request_error == "Kafka down"
