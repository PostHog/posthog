"""Tests for batch trace summarization workflow."""

import uuid
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from posthog.temporal.llm_analytics.trace_summarization.embedding import (
    embed_summaries_activity,
    format_summary_for_embedding,
)
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs, TraceSummary
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
        inputs = BatchSummarizationInputs(team_id=mock_team.id, max_traces=100, window_minutes=60)

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
            # Create traces from window
            mock_traces = [
                LLMTrace(id=f"trace_{i}", createdAt=datetime.now(UTC).isoformat(), events=[], person=mock_person)
                for i in range(50)
            ]
            mock_runner.calculate.return_value.results = mock_traces

            result = await query_traces_in_window_activity(inputs)

            assert len(result) == 50
            assert result[0]["trace_id"] == "trace_0"
            assert result[0]["team_id"] == mock_team.id
            assert "trace_timestamp" in result[0]

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_query_traces_empty(self, mock_team):
        """Test querying when no traces found in window."""
        inputs = BatchSummarizationInputs(team_id=mock_team.id, max_traces=100, window_minutes=60)

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
            patch("products.llm_analytics.backend.summarization.llm.summarize") as mock_summarize,
            patch("products.llm_analytics.backend.text_repr.formatters.format_trace_text_repr") as mock_format,
            patch("posthog.hogql_queries.ai.trace_query_runner.TraceQueryRunner") as mock_runner_class,
            patch("posthog.models.event.util.create_event") as mock_create_event,
        ):
            # Mock trace query runner
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

            mock_format.return_value = "L1: Test trace\nL2: Content"
            mock_summarize.return_value = mock_summary

            result = await generate_and_save_summary_activity(
                sample_trace_data["trace_id"],
                mock_team.id,
                sample_trace_data["trace_timestamp"],
                "minimal",
                "test_batch_run_id",
                None,
            )

            assert result["success"] is True
            assert result["trace_id"] == sample_trace_data["trace_id"]
            assert "text_repr_length" in result
            assert "event_count" in result

            # Verify create_event was called with flattened properties
            mock_create_event.assert_called_once()
            call_kwargs = mock_create_event.call_args.kwargs
            assert call_kwargs["properties"]["$ai_trace_id"] == sample_trace_data["trace_id"]
            assert call_kwargs["properties"]["$ai_summary_title"] == "Test Summary"


class TestFormatSummaryForEmbedding:
    """Tests for format_summary_for_embedding function."""

    def test_format_full_summary(self):
        """Test formatting a complete summary with all fields."""
        from products.llm_analytics.backend.summarization.llm.schema import (
            InterestingNote,
            SummarizationResponse,
            SummaryBullet,
        )

        summary = TraceSummary(
            trace_id="trace_123",
            text_repr="L1: Test trace\nL2: Content",
            summary=SummarizationResponse(
                title="User Authentication Flow",
                flow_diagram="graph TD;\nA[Login] --> B{Auth};\nB -->|Success| C[Dashboard];",
                summary_bullets=[
                    SummaryBullet(text="User logged in successfully", line_refs="L5"),
                    SummaryBullet(text="Session created with 1h expiry", line_refs="L12"),
                ],
                interesting_notes=[
                    InterestingNote(text="Using JWT for authentication", line_refs="L20"),
                    InterestingNote(text="Redis for session storage", line_refs="L25"),
                ],
            ),
            metadata={"mode": "detailed"},
        )

        result = format_summary_for_embedding(summary)

        assert "Title: User Authentication Flow" in result
        assert "graph TD;" in result
        assert "User logged in successfully" in result
        assert "Session created with 1h expiry" in result
        assert "Using JWT for authentication" in result
        assert "Redis for session storage" in result
        # Line refs should NOT be in the output
        assert "L5" not in result
        assert "L12" not in result
        assert "L20" not in result
        assert "L25" not in result

    def test_format_minimal_summary(self):
        """Test formatting a minimal summary with no notes."""
        from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse, SummaryBullet

        summary = TraceSummary(
            trace_id="trace_456",
            text_repr="Test",
            summary=SummarizationResponse(
                title="Simple API Call",
                flow_diagram="A -> B",
                summary_bullets=[SummaryBullet(text="GET request to /api/users", line_refs="L1")],
                interesting_notes=[],
            ),
            metadata={"mode": "minimal"},
        )

        result = format_summary_for_embedding(summary)

        assert "Title: Simple API Call" in result
        assert "GET request to /api/users" in result
        assert "Interesting Notes:" not in result


class TestEmbedSummariesActivity:
    """Tests for embed_summaries_activity."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_embed_summaries_success(self, mock_team):
        """Test successful embedding of summaries."""
        from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse, SummaryBullet

        summaries = [
            TraceSummary(
                trace_id="trace_1",
                text_repr="L1: Test content",
                summary=SummarizationResponse(
                    title="Summary 1",
                    flow_diagram="A -> B",
                    summary_bullets=[SummaryBullet(text="Bullet 1", line_refs="L1")],
                    interesting_notes=[],
                ),
                metadata={"mode": "detailed"},
            ),
            TraceSummary(
                trace_id="trace_2",
                text_repr="L1: More content",
                summary=SummarizationResponse(
                    title="Summary 2",
                    flow_diagram="C -> D",
                    summary_bullets=[SummaryBullet(text="Bullet 2", line_refs="L2")],
                    interesting_notes=[],
                ),
                metadata={"mode": "detailed"},
            ),
        ]

        with patch(
            "ee.hogai.llm_traces_summaries.tools.embed_summaries.LLMTracesSummarizerEmbedder"
        ) as mock_embedder_class:
            mock_embedder = mock_embedder_class.return_value

            result = await embed_summaries_activity(summaries, mock_team.id, "detailed")

            assert result["embeddings_requested"] == 2
            assert result["embeddings_failed"] == 0
            assert mock_embedder._embed_document.call_count == 2

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_embed_summaries_failure_threshold(self, mock_team):
        """Test that >10% failure rate raises error."""
        from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse, SummaryBullet

        # Create 10 summaries
        summaries = [
            TraceSummary(
                trace_id=f"trace_{i}",
                text_repr="Test",
                summary=SummarizationResponse(
                    title=f"Summary {i}",
                    flow_diagram="A -> B",
                    summary_bullets=[SummaryBullet(text="Bullet", line_refs="L1")],
                    interesting_notes=[],
                ),
                metadata={"mode": "minimal"},
            )
            for i in range(10)
        ]

        # Mock formatting to fail for 2 summaries (20% > 10% threshold)
        with patch(
            "posthog.temporal.llm_analytics.trace_summarization.embedding.format_summary_for_embedding"
        ) as mock_format:
            mock_format.side_effect = [
                "formatted_0",
                Exception("Error 1"),
                "formatted_2",
                "formatted_3",
                "formatted_4",
                "formatted_5",
                "formatted_6",
                "formatted_7",
                "formatted_8",
                Exception("Error 2"),
            ]

            with pytest.raises(ValueError, match="Exceeds 10% threshold"):
                await embed_summaries_activity(summaries, mock_team.id, "minimal")

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_embed_summaries_team_not_found(self):
        """Test embedding when team doesn't exist."""
        from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse

        summaries = [
            TraceSummary(
                trace_id="trace_1",
                text_repr="Test",
                summary=SummarizationResponse(
                    title="Test",
                    flow_diagram="",
                    summary_bullets=[],
                    interesting_notes=[],
                ),
                metadata={},
            )
        ]

        with pytest.raises(ValueError, match="Team 99999 not found"):
            await embed_summaries_activity(summaries, 99999, "minimal")


class TestBatchTraceSummarizationWorkflow:
    """Tests for BatchTraceSummarizationWorkflow."""

    def test_parse_inputs_minimal(self):
        """Test parsing minimal inputs."""
        inputs = BatchTraceSummarizationWorkflow.parse_inputs(["123"])

        assert inputs.team_id == 123
        assert inputs.max_traces == 100
        assert inputs.batch_size == 10
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
