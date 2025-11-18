"""Tests for batch trace summarization workflow."""

import uuid
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from posthog.temporal.llm_analytics.trace_summarization.events import emit_trace_summary_events_activity
from posthog.temporal.llm_analytics.trace_summarization.fetching import fetch_trace_hierarchy_activity
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs, TraceSummary
from posthog.temporal.llm_analytics.trace_summarization.sampling import sample_recent_traces_activity
from posthog.temporal.llm_analytics.trace_summarization.summarization import generate_summary_activity
from posthog.temporal.llm_analytics.trace_summarization.workflows import BatchTraceSummarizationWorkflow


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


class TestSampleRecentTracesActivity:
    """Tests for sample_recent_traces_activity."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_traces_success(self, mock_team):
        """Test successful trace sampling."""
        inputs = BatchSummarizationInputs(team_id=mock_team.id, sample_size=10)

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
            # Create 100+ traces to satisfy MIN_SAMPLE_SIZE threshold
            mock_traces = [
                LLMTrace(id=f"trace_{i}", createdAt=datetime.now(UTC).isoformat(), events=[], person=mock_person)
                for i in range(150)
            ]
            mock_runner.calculate.return_value.results = mock_traces

            result = await sample_recent_traces_activity(inputs)

            assert len(result) == 150
            assert result[0]["trace_id"] == "trace_0"
            assert result[0]["team_id"] == mock_team.id
            assert "trace_timestamp" in result[0]

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_traces_empty(self, mock_team):
        """Test sampling when no traces found."""
        inputs = BatchSummarizationInputs(team_id=mock_team.id, sample_size=10)

        with patch(
            "posthog.temporal.llm_analytics.trace_summarization.sampling.TracesQueryRunner"
        ) as mock_runner_class:
            mock_runner = mock_runner_class.return_value
            mock_runner.calculate.return_value.results = []

            result = await sample_recent_traces_activity(inputs)

            assert len(result) == 0


class TestFetchTraceHierarchyActivity:
    """Tests for fetch_trace_hierarchy_activity."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_fetch_hierarchy_success(self, sample_trace_data, mock_team):
        """Test successful trace hierarchy fetching."""
        trace_id = sample_trace_data["trace_id"]
        team_id = mock_team.id
        timestamp = sample_trace_data["trace_timestamp"]

        with patch("posthog.temporal.llm_analytics.trace_summarization.fetching.TraceQueryRunner") as mock_runner_class:
            from posthog.schema import LLMTrace, LLMTraceEvent, LLMTracePerson

            mock_person = LLMTracePerson(
                uuid=str(uuid.uuid4()),
                distinct_id="test_user",
                created_at=datetime.now(UTC).isoformat(),
                properties={},
            )

            mock_runner = mock_runner_class.return_value
            mock_runner.calculate.return_value.results = [
                LLMTrace(
                    id=trace_id,
                    createdAt=datetime.now(UTC).isoformat(),
                    traceName="Test Trace",
                    aiSessionId="session_1",
                    inputState={"key": "value"},
                    outputState={"result": "output"},
                    person=mock_person,
                    events=[
                        LLMTraceEvent(
                            id=str(uuid.uuid4()),
                            event="$ai_generation",
                            properties={"$ai_model": "gpt-4"},
                            createdAt=datetime.now(UTC).isoformat(),
                        )
                    ],
                )
            ]

            result = await fetch_trace_hierarchy_activity(trace_id, team_id, timestamp)

            assert "trace" in result
            assert "hierarchy" in result
            assert result["trace"]["properties"]["$ai_trace_id"] == trace_id
            assert len(result["hierarchy"]) == 1

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_fetch_hierarchy_no_events(self, sample_trace_data, mock_team):
        """Test fetching when no events found."""
        with patch("posthog.temporal.llm_analytics.trace_summarization.fetching.TraceQueryRunner") as mock_runner_class:
            mock_runner = mock_runner_class.return_value
            mock_runner.calculate.return_value.results = []

            with pytest.raises(ValueError, match="No events found"):
                await fetch_trace_hierarchy_activity(
                    sample_trace_data["trace_id"],
                    mock_team.id,
                    sample_trace_data["trace_timestamp"],
                )


class TestGenerateSummaryActivity:
    """Tests for generate_summary_activity."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_generate_summary_success(self, sample_trace_hierarchy, mock_team):
        """Test successful summary generation."""
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
        ):
            mock_format.return_value = "L1: Test trace\nL2: Content"
            mock_summarize.return_value = mock_summary

            result = await generate_summary_activity(sample_trace_hierarchy, mock_team.id, "minimal")

            assert isinstance(result, TraceSummary)
            assert result.trace_id == sample_trace_hierarchy["trace"]["properties"]["$ai_trace_id"]
            assert result.summary.title == "Test Summary"
            assert result.metadata["mode"] == "minimal"


class TestEmitTraceSummaryEventsActivity:
    """Tests for emit_trace_summary_events_activity."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_emit_events_success(self, mock_team):
        """Test successful event emission."""
        from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse, SummaryBullet

        summaries = [
            TraceSummary(
                trace_id="trace_1",
                text_repr="L1: Test content",
                summary=SummarizationResponse(
                    title="Summary 1",
                    flow_diagram="graph TD; A-->B;",
                    summary_bullets=[SummaryBullet(text="Bullet", line_refs="L1")],
                    interesting_notes=[],
                ),
                metadata={"text_repr_length": 100, "mode": "minimal", "event_count": 5},
            )
        ]

        with patch("posthog.temporal.llm_analytics.trace_summarization.events.create_event") as mock_create:
            result = await emit_trace_summary_events_activity(summaries, mock_team.id, "test_batch_123")

            assert result == 1
            assert mock_create.call_count == 1

            call_args = mock_create.call_args
            assert call_args[1]["event"] == "$ai_trace_summary"
            assert call_args[1]["properties"]["$ai_trace_id"] == "trace_1"
            assert call_args[1]["properties"]["$ai_batch_run_id"] == "test_batch_123"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_emit_events_team_not_found(self):
        """Test event emission when team doesn't exist."""
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
            await emit_trace_summary_events_activity(summaries, 99999, "test_batch")


class TestBatchTraceSummarizationWorkflow:
    """Tests for BatchTraceSummarizationWorkflow."""

    def test_parse_inputs_minimal(self):
        """Test parsing minimal inputs."""
        inputs = BatchTraceSummarizationWorkflow.parse_inputs(["123"])

        assert inputs.team_id == 123
        assert inputs.sample_size == 1000
        assert inputs.batch_size == 100
        assert inputs.mode == "minimal"

    def test_parse_inputs_full(self):
        """Test parsing full inputs."""
        inputs = BatchTraceSummarizationWorkflow.parse_inputs(
            ["123", "500", "50", "detailed", "2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"]
        )

        assert inputs.team_id == 123
        assert inputs.sample_size == 500
        assert inputs.batch_size == 50
        assert inputs.mode == "detailed"
        assert inputs.start_date == "2025-01-01T00:00:00Z"
        assert inputs.end_date == "2025-01-02T00:00:00Z"
