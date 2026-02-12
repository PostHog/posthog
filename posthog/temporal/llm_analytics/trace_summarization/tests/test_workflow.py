"""Tests for batch trace summarization workflow and sampling."""

from contextlib import asynccontextmanager

import pytest
from unittest.mock import patch

from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs, SampledItem
from posthog.temporal.llm_analytics.trace_summarization.sampling import sample_items_in_window_activity
from posthog.temporal.llm_analytics.trace_summarization.workflow import BatchTraceSummarizationWorkflow


@asynccontextmanager
async def _noop_heartbeater(*args, **kwargs):
    yield


@pytest.fixture
def mock_team(db):
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    organization = Organization.objects.create(name="Test Org")
    team = Team.objects.create(
        organization=organization,
        name="Test Team",
    )
    return team


@patch(
    "posthog.temporal.llm_analytics.trace_summarization.sampling.Heartbeater",
    _noop_heartbeater,
)
class TestSampleItemsInWindowActivity:
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_traces_success(self, mock_team):
        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=100,
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
        )

        mock_results = [[f"trace_{i}", f"2025-01-15T11:{i:02d}:00+00:00"] for i in range(50)]

        with patch("posthog.temporal.llm_analytics.trace_summarization.sampling.execute_hogql_query") as mock_execute:
            mock_execute.return_value.results = mock_results

            result = await sample_items_in_window_activity(inputs)

            assert len(result) == 50
            assert isinstance(result[0], SampledItem)
            assert result[0].trace_id == "trace_0"
            assert result[0].generation_id is None
            assert result[49].trace_id == "trace_49"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_traces_passes_size_filter(self, mock_team):
        from posthog.temporal.llm_analytics.trace_summarization.constants import (
            MAX_TRACE_EVENTS_LIMIT,
            MAX_TRACE_PROPERTIES_SIZE,
        )

        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=10,
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
        )

        with patch("posthog.temporal.llm_analytics.trace_summarization.sampling.execute_hogql_query") as mock_execute:
            mock_execute.return_value.results = []

            await sample_items_in_window_activity(inputs)

            placeholders = mock_execute.call_args.kwargs["placeholders"]
            assert placeholders["max_events"].value == MAX_TRACE_EVENTS_LIMIT
            assert placeholders["max_properties_size"].value == MAX_TRACE_PROPERTIES_SIZE

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_generations_success(self, mock_team):
        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=50,
            analysis_level="generation",
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
        )

        mock_results = [[f"trace_{i}", f"gen-uuid-{i}", f"2025-01-15T11:{i:02d}:00+00:00"] for i in range(10)]

        with patch("posthog.temporal.llm_analytics.trace_summarization.sampling.execute_hogql_query") as mock_execute:
            mock_execute.return_value.results = mock_results

            result = await sample_items_in_window_activity(inputs)

            assert len(result) == 10
            assert isinstance(result[0], SampledItem)
            assert result[0].trace_id == "trace_0"
            assert result[0].generation_id == "gen-uuid-0"

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_generations_passes_size_filter(self, mock_team):
        from posthog.temporal.llm_analytics.trace_summarization.constants import (
            MAX_TRACE_EVENTS_LIMIT,
            MAX_TRACE_PROPERTIES_SIZE,
        )

        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=50,
            analysis_level="generation",
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
        )

        with patch("posthog.temporal.llm_analytics.trace_summarization.sampling.execute_hogql_query") as mock_execute:
            mock_execute.return_value.results = []

            await sample_items_in_window_activity(inputs)

            placeholders = mock_execute.call_args.kwargs["placeholders"]
            assert placeholders["max_events"].value == MAX_TRACE_EVENTS_LIMIT
            assert placeholders["max_properties_size"].value == MAX_TRACE_PROPERTIES_SIZE

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_sample_items_empty(self, mock_team):
        inputs = BatchSummarizationInputs(
            team_id=mock_team.id,
            max_items=100,
            window_minutes=60,
            window_start="2025-01-15T11:00:00",
            window_end="2025-01-15T12:00:00",
        )

        with patch("posthog.temporal.llm_analytics.trace_summarization.sampling.execute_hogql_query") as mock_execute:
            mock_execute.return_value.results = []

            result = await sample_items_in_window_activity(inputs)

            assert len(result) == 0


class TestBatchTraceSummarizationWorkflow:
    def test_parse_inputs_minimal(self):
        inputs = BatchTraceSummarizationWorkflow.parse_inputs(["123"])

        assert inputs.team_id == 123
        assert inputs.analysis_level == "trace"
        assert inputs.max_items == 15
        assert inputs.batch_size == 5
        assert inputs.mode == "detailed"
        assert inputs.window_minutes == 60

    def test_parse_inputs_full_trace_level(self):
        inputs = BatchTraceSummarizationWorkflow.parse_inputs(
            ["123", "trace", "200", "20", "detailed", "30", "2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"]
        )

        assert inputs.team_id == 123
        assert inputs.analysis_level == "trace"
        assert inputs.max_items == 200
        assert inputs.batch_size == 20
        assert inputs.mode == "detailed"
        assert inputs.window_minutes == 30
        assert inputs.window_start == "2025-01-01T00:00:00Z"
        assert inputs.window_end == "2025-01-02T00:00:00Z"

    def test_parse_inputs_full_generation_level(self):
        inputs = BatchTraceSummarizationWorkflow.parse_inputs(
            ["123", "generation", "200", "20", "detailed", "30", "2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"]
        )

        assert inputs.team_id == 123
        assert inputs.analysis_level == "generation"
        assert inputs.max_items == 200
        assert inputs.batch_size == 20
        assert inputs.mode == "detailed"
        assert inputs.window_minutes == 30
        assert inputs.window_start == "2025-01-01T00:00:00Z"
        assert inputs.window_end == "2025-01-02T00:00:00Z"
