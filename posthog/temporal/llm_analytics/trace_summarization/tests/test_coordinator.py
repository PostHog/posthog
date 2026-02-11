"""Tests for batch trace summarization coordinator workflow."""

import pytest

from posthog.temporal.llm_analytics.trace_summarization.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_ITEMS_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    DEFAULT_WINDOW_MINUTES,
)
from posthog.temporal.llm_analytics.trace_summarization.coordinator import (
    BatchTraceSummarizationCoordinatorInputs,
    BatchTraceSummarizationCoordinatorWorkflow,
)

from products.llm_analytics.backend.summarization.models import SummarizationMode


class TestBatchTraceSummarizationCoordinatorWorkflow:
    """Tests for BatchTraceSummarizationCoordinatorWorkflow."""

    @pytest.mark.parametrize(
        "inputs,expected",
        [
            pytest.param(
                [],
                BatchTraceSummarizationCoordinatorInputs(
                    analysis_level="trace",
                    max_items=DEFAULT_MAX_ITEMS_PER_WINDOW,
                    batch_size=DEFAULT_BATCH_SIZE,
                    mode=DEFAULT_MODE,
                    window_minutes=DEFAULT_WINDOW_MINUTES,
                    model=DEFAULT_MODEL,
                ),
                id="empty_inputs_uses_defaults",
            ),
            pytest.param(
                ["trace", "200"],
                BatchTraceSummarizationCoordinatorInputs(
                    analysis_level="trace",
                    max_items=200,
                    batch_size=DEFAULT_BATCH_SIZE,
                    mode=DEFAULT_MODE,
                    window_minutes=DEFAULT_WINDOW_MINUTES,
                    model=DEFAULT_MODEL,
                ),
                id="trace_level_with_max_traces",
            ),
            pytest.param(
                ["generation", "200"],
                BatchTraceSummarizationCoordinatorInputs(
                    analysis_level="generation",
                    max_items=200,
                    batch_size=DEFAULT_BATCH_SIZE,
                    mode=DEFAULT_MODE,
                    window_minutes=DEFAULT_WINDOW_MINUTES,
                    model=DEFAULT_MODEL,
                ),
                id="generation_level_with_max_traces",
            ),
            pytest.param(
                ["trace", "200", "20", "detailed", "30", "gpt-4.1-mini"],
                BatchTraceSummarizationCoordinatorInputs(
                    analysis_level="trace",
                    max_items=200,
                    batch_size=20,
                    mode=SummarizationMode.DETAILED,
                    window_minutes=30,
                    model="gpt-4.1-mini",
                ),
                id="full_inputs",
            ),
        ],
    )
    def test_parse_inputs(self, inputs, expected):
        result = BatchTraceSummarizationCoordinatorWorkflow.parse_inputs(inputs)

        assert result.analysis_level == expected.analysis_level
        assert result.max_items == expected.max_items
        assert result.batch_size == expected.batch_size
        assert result.mode == expected.mode
        assert result.window_minutes == expected.window_minutes
        assert result.model == expected.model
