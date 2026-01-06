"""Tests for batch trace summarization workflow."""

import uuid
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs
from posthog.temporal.llm_analytics.trace_summarization.sampling import query_traces_in_window_activity
from posthog.temporal.llm_analytics.trace_summarization.summarization import generate_and_save_summary_activity
from posthog.temporal.llm_analytics.trace_summarization.workflow import BatchTraceSummarizationWorkflow


@pytest.fixture
def mock_team(db):
    """Create a test team."""
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    organization = Organization.objects.create(name="Test Org")
    team = Team.objects.create(
        organization=organization,
        name="Test Team",
    )
    return team


@pytest.fixture
def sample_trace_data():
    """Sample trace data for testing."""
    trace_id = str(uuid.uuid4())
    return {
        "trace_id": trace_id,
        "trace_timestamp": datetime.now(UTC).isoformat(),
        "team_id": 1,
    }


@pytest.fixture
def sample_trace_hierarchy(sample_trace_data):
    """Sample trace hierarchy for testing."""
    trace_id = sample_trace_data["trace_id"]
    return {
        "trace": {
            "id": trace_id,
            "event": "$ai_trace",
            "properties": {
                "$ai_trace_id": trace_id,
                "$ai_span_name": "Test Trace",
            },
        },
        "hierarchy": [
            {
                "event": {
                    "id": str(uuid.uuid4()),
                    "event": "$ai_generation",
                    "properties": {
                        "$ai_trace_id": trace_id,
                        "$ai_span_name": "Test Generation",
                        "$ai_model": "gpt-4",
                        "$ai_input": [{"role": "user", "content": "Hello"}],
                        "$ai_output_choices": [{"message": {"role": "assistant", "content": "Hi there!"}}],
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                "children": [],
            }
        ],
    }


class TestQueryTracesInWindowActivity:
    """Tests for query_traces_in_window_activity."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_query_traces_success(self, mock_team):
        """Test successful trace querying from window."""
        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_traces=100,
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
        )

        with patch(
            "posthog.temporal.llm_analytics.trace_summarization.sampling.TracesQueryRunner"
        ) as mock_runner_class:
            from posthog.schema import LLMTrace, LLMTracePerson

            mock_person = LLMTracePerson(
                uuid=str(uuid.uuid4()),
                distinct_id="test_user",
                created_at=datetime.now(UTC).isoformat(),
                properties={},
            )

            mock_runner = mock_runner_class.return_value
            mock_traces = [
                LLMTrace(id=f"trace_{i}", createdAt=datetime.now(UTC).isoformat(), events=[], person=mock_person)
                for i in range(50)
            ]
            mock_runner.calculate.return_value.results = mock_traces

            result = await query_traces_in_window_activity(inputs)

            assert len(result) == 50
            assert result[0] == "trace_0"
            assert result[49] == "trace_49"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_query_traces_empty(self, mock_team):
        """Test querying when no traces found in window."""
        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_traces=100,
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
        )

        with patch(
            "posthog.temporal.llm_analytics.trace_summarization.sampling.TracesQueryRunner"
        ) as mock_runner_class:
            mock_runner = mock_runner_class.return_value
            mock_runner.calculate.return_value.results = []

            result = await query_traces_in_window_activity(inputs)

            assert len(result) == 0


class TestGenerateSummaryActivity:
    """Tests for generate_and_save_summary_activity."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_generate_and_save_summary_success(self, sample_trace_data, mock_team):
        """Test successful summary generation and saving."""
        from posthog.schema import LLMTrace, LLMTracePerson

        from products.llm_analytics.backend.summarization.llm.schema import (
            InterestingNote,
            SummarizationResponse,
            SummaryBullet,
        )

        mock_summary = SummarizationResponse(
            title="Test Summary",
            flow_diagram="graph TD; A-->B;",
            summary_bullets=[SummaryBullet(text="Bullet 1", line_refs="L1-2")],
            interesting_notes=[InterestingNote(text="Note 1", line_refs="L5")],
        )

        with (
            patch("posthog.temporal.llm_analytics.trace_summarization.summarization.summarize") as mock_summarize,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarization.llm_trace_to_formatter_format"
            ) as mock_to_format,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarization.format_trace_text_repr"
            ) as mock_format,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarization.TraceQueryRunner"
            ) as mock_runner_class,
            patch("posthog.temporal.llm_analytics.trace_summarization.summarization.create_event") as mock_create_event,
        ):
            mock_person = LLMTracePerson(
                uuid=str(uuid.uuid4()),
                distinct_id="test_user",
                created_at=datetime.now(UTC).isoformat(),
                properties={},
            )
            mock_trace = LLMTrace(
                id=sample_trace_data["trace_id"],
                createdAt=sample_trace_data["trace_timestamp"],
                events=[],
                person=mock_person,
            )
            mock_runner = mock_runner_class.return_value
            mock_runner.calculate.return_value.results = [mock_trace]

            mock_to_format.return_value = ({"id": sample_trace_data["trace_id"], "properties": {}}, [])
            mock_format.return_value = ("L1: Test trace\nL2: Content", False)
            mock_summarize.return_value = mock_summary

            result = await generate_and_save_summary_activity(
                sample_trace_data["trace_id"],
                mock_team.id,
                "2025-01-01T00:00:00Z",  # window_start
                "2025-01-01T01:00:00Z",  # window_end
                "minimal",
                "test_batch_run_id",
                "openai",
            )

            assert result.success is True
            assert result.trace_id == sample_trace_data["trace_id"]
            assert result.text_repr_length > 0
            assert result.event_count >= 0

            mock_create_event.assert_called_once()
            call_kwargs = mock_create_event.call_args.kwargs
            assert call_kwargs["properties"]["$ai_trace_id"] == sample_trace_data["trace_id"]
            assert call_kwargs["properties"]["$ai_summary_title"] == "Test Summary"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_embedding_requested_on_success(self, sample_trace_data, mock_team):
        from posthog.schema import LLMTrace, LLMTracePerson

        from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse

        mock_summary = SummarizationResponse(title="Test", flow_diagram="", summary_bullets=[], interesting_notes=[])

        with (
            patch("posthog.temporal.llm_analytics.trace_summarization.summarization.summarize") as mock_summarize,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarization.llm_trace_to_formatter_format"
            ) as mock_to_format,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarization.format_trace_text_repr"
            ) as mock_format,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarization.TraceQueryRunner"
            ) as mock_runner_class,
            patch("posthog.temporal.llm_analytics.trace_summarization.summarization.create_event"),
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarization.LLMTracesSummarizerEmbedder"
            ) as mock_embedder_class,
        ):
            mock_person = LLMTracePerson(
                uuid=str(uuid.uuid4()), distinct_id="test", created_at=datetime.now(UTC).isoformat(), properties={}
            )
            mock_trace = LLMTrace(
                id=sample_trace_data["trace_id"],
                createdAt=sample_trace_data["trace_timestamp"],
                events=[],
                person=mock_person,
            )
            mock_runner_class.return_value.calculate.return_value.results = [mock_trace]
            mock_to_format.return_value = ({}, [])
            mock_format.return_value = ("test", False)
            mock_summarize.return_value = mock_summary

            result = await generate_and_save_summary_activity(
                sample_trace_data["trace_id"],
                mock_team.id,
                "2025-01-01T00:00:00Z",
                "2025-01-01T01:00:00Z",
                "minimal",
                "batch_123",
                "openai",
            )

            assert result.embedding_requested is True
            assert result.embedding_request_error is None
            mock_embedder_class.return_value._embed_document.assert_called_once()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_embedding_failure_captured(self, sample_trace_data, mock_team):
        from posthog.schema import LLMTrace, LLMTracePerson

        from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse

        mock_summary = SummarizationResponse(title="Test", flow_diagram="", summary_bullets=[], interesting_notes=[])

        with (
            patch("posthog.temporal.llm_analytics.trace_summarization.summarization.summarize") as mock_summarize,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarization.llm_trace_to_formatter_format"
            ) as mock_to_format,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarization.format_trace_text_repr"
            ) as mock_format,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarization.TraceQueryRunner"
            ) as mock_runner_class,
            patch("posthog.temporal.llm_analytics.trace_summarization.summarization.create_event"),
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.summarization.LLMTracesSummarizerEmbedder"
            ) as mock_embedder_class,
        ):
            mock_person = LLMTracePerson(
                uuid=str(uuid.uuid4()), distinct_id="test", created_at=datetime.now(UTC).isoformat(), properties={}
            )
            mock_trace = LLMTrace(
                id=sample_trace_data["trace_id"],
                createdAt=sample_trace_data["trace_timestamp"],
                events=[],
                person=mock_person,
            )
            mock_runner_class.return_value.calculate.return_value.results = [mock_trace]
            mock_to_format.return_value = ({}, [])
            mock_format.return_value = ("test", False)
            mock_summarize.return_value = mock_summary
            mock_embedder_class.return_value._embed_document.side_effect = Exception("Kafka connection failed")

            result = await generate_and_save_summary_activity(
                sample_trace_data["trace_id"],
                mock_team.id,
                "2025-01-01T00:00:00Z",
                "2025-01-01T01:00:00Z",
                "minimal",
                "batch_123",
                "openai",
            )

            assert result.success is True  # Summary saved successfully
            assert result.embedding_requested is False
            assert result.embedding_request_error == "Kafka connection failed"


class TestBatchTraceSummarizationWorkflow:
    """Tests for BatchTraceSummarizationWorkflow."""

    def test_parse_inputs_minimal(self):
        """Test parsing minimal inputs."""
        inputs = BatchTraceSummarizationWorkflow.parse_inputs(["123"])

        assert inputs.team_id == 123
        assert inputs.max_traces == 100
        assert inputs.batch_size == 5
        assert inputs.mode == "detailed"
        assert inputs.window_minutes == 60

    def test_parse_inputs_full(self):
        """Test parsing full inputs."""
        inputs = BatchTraceSummarizationWorkflow.parse_inputs(
            ["123", "200", "20", "detailed", "30", "2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"]
        )

        assert inputs.team_id == 123
        assert inputs.max_traces == 200
        assert inputs.batch_size == 20
        assert inputs.mode == "detailed"
        assert inputs.window_minutes == 30
        assert inputs.window_start == "2025-01-01T00:00:00Z"
        assert inputs.window_end == "2025-01-02T00:00:00Z"
