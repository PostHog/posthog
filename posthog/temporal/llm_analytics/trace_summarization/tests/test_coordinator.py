"""Tests for batch trace summarization coordinator workflow."""

import pytest
from unittest.mock import patch

from posthog.temporal.llm_analytics.trace_summarization.constants import (
    ALLOWED_TEAM_IDS,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_TRACES_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_WINDOW_MINUTES,
)
from posthog.temporal.llm_analytics.trace_summarization.coordinator import (
    BatchTraceSummarizationCoordinatorInputs,
    BatchTraceSummarizationCoordinatorWorkflow,
    get_allowed_team_ids,
)

from products.llm_analytics.backend.summarization.models import SummarizationMode, SummarizationProvider


class TestGetAllowedTeamIds:
    """Tests for get_allowed_team_ids function."""

    def test_returns_copy_of_allowed_team_ids(self):
        """Test that function returns a copy of ALLOWED_TEAM_IDS."""
        result = get_allowed_team_ids()
        assert result == ALLOWED_TEAM_IDS
        assert result is not ALLOWED_TEAM_IDS

    def test_returns_empty_list_when_no_teams_configured(self):
        """Test that function returns empty list when ALLOWED_TEAM_IDS is empty."""
        with patch(
            "posthog.temporal.llm_analytics.trace_summarization.coordinator.ALLOWED_TEAM_IDS",
            [],
        ):
            result = get_allowed_team_ids()
            assert result == []


class TestBatchTraceSummarizationCoordinatorWorkflow:
    """Tests for BatchTraceSummarizationCoordinatorWorkflow."""

    @pytest.mark.parametrize(
        "inputs,expected",
        [
            pytest.param(
                [],
                BatchTraceSummarizationCoordinatorInputs(
                    max_traces=DEFAULT_MAX_TRACES_PER_WINDOW,
                    batch_size=DEFAULT_BATCH_SIZE,
                    mode=DEFAULT_MODE,
                    window_minutes=DEFAULT_WINDOW_MINUTES,
                    provider=DEFAULT_PROVIDER,
                    model=DEFAULT_MODEL,
                ),
                id="empty_inputs_uses_defaults",
            ),
            pytest.param(
                ["200"],
                BatchTraceSummarizationCoordinatorInputs(
                    max_traces=200,
                    batch_size=DEFAULT_BATCH_SIZE,
                    mode=DEFAULT_MODE,
                    window_minutes=DEFAULT_WINDOW_MINUTES,
                    provider=DEFAULT_PROVIDER,
                    model=DEFAULT_MODEL,
                ),
                id="single_input_sets_max_traces",
            ),
            pytest.param(
                ["200", "20", "detailed", "30", "openai", "gpt-4.1-mini"],
                BatchTraceSummarizationCoordinatorInputs(
                    max_traces=200,
                    batch_size=20,
                    mode=SummarizationMode.DETAILED,
                    window_minutes=30,
                    provider=SummarizationProvider.OPENAI,
                    model="gpt-4.1-mini",
                ),
                id="full_inputs",
            ),
        ],
    )
    def test_parse_inputs(self, inputs, expected):
        """Test parsing of workflow inputs."""
        result = BatchTraceSummarizationCoordinatorWorkflow.parse_inputs(inputs)

        assert result.max_traces == expected.max_traces
        assert result.batch_size == expected.batch_size
        assert result.mode == expected.mode
        assert result.window_minutes == expected.window_minutes
        assert result.provider == expected.provider
        assert result.model == expected.model
