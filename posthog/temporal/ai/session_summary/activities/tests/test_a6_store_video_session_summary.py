"""
Tests for Activity 6: store_video_session_summary_activity

This activity converts video segments to session summary format and stores in database.
"""

import json
import dataclasses
from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.models import Team
from posthog.models.user import User
from posthog.temporal.ai.session_summary.activities.a6_store_video_session_summary import (
    _find_closest_event,
    _parse_timestamp_to_ms,
    store_video_session_summary_activity,
)
from posthog.temporal.ai.session_summary.state import _compress_redis_data
from posthog.temporal.ai.session_summary.types.video import ConsolidatedVideoAnalysis

from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.models.session_summaries import SingleSessionSummary

pytestmark = pytest.mark.django_db


class TestParseTimestampToMs:
    """Unit tests for _parse_timestamp_to_ms helper function."""

    @pytest.mark.parametrize(
        ("timestamp_str", "expected_ms"),
        [
            ("00:00", 0),
            ("00:01", 1000),
            ("00:30", 30000),
            ("01:00", 60000),
            ("01:30", 90000),
            ("02:00", 120000),
            ("10:00", 600000),
            ("00:00:00", 0),
            ("00:01:00", 60000),
            ("01:00:00", 3600000),
            ("01:30:45", 5445000),
        ],
    )
    def test_parse_timestamp_to_ms(self, timestamp_str: str, expected_ms: int):
        """Test various timestamp formats."""
        assert _parse_timestamp_to_ms(timestamp_str) == expected_ms

    @pytest.mark.parametrize(
        "invalid_timestamp",
        [
            "invalid",
            "00",
            "1:2:3:4",
            "",
        ],
    )
    def test_parse_timestamp_to_ms_invalid_format(self, invalid_timestamp: str):
        """Test that invalid formats raise ValueError."""
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            _parse_timestamp_to_ms(invalid_timestamp)


class TestFindClosestEvent:
    """Unit tests for _find_closest_event helper function."""

    @pytest.fixture
    def sample_events_mapping(self) -> dict[str, list[Any]]:
        """Sample events mapping for testing."""
        return {
            "event_001": [
                "event_001",
                0,
                "$pageview",
                "2025-03-31T18:40:35.000000+00:00",
                "click",
                "url_1",
                "window_1",
            ],
            "event_002": [
                "event_002",
                1,
                "$autocapture",
                "2025-03-31T18:40:50.000000+00:00",
                "click",
                "url_1",
                "window_1",
            ],
            "event_003": [
                "event_003",
                2,
                "$autocapture",
                "2025-03-31T18:41:20.000000+00:00",
                "submit",
                "url_2",
                "window_1",
            ],
        }

    @pytest.fixture
    def sample_events_columns(self) -> list[str]:
        """Sample events columns for testing."""
        return ["event_id", "event_index", "event", "timestamp", "$event_type", "$current_url", "$window_id"]

    def test_find_closest_event_exact_match(
        self, sample_events_mapping: dict[str, list[Any]], sample_events_columns: list[str]
    ):
        """Test finding event with exact timestamp match."""
        session_start_time_str = "2025-03-31T18:40:32.302000+00:00"

        # Event_001 is at ~3s from start
        result = _find_closest_event(
            target_ms=3000,
            simplified_events_mapping=sample_events_mapping,
            simplified_events_columns=sample_events_columns,
            session_start_time_str=session_start_time_str,
        )

        assert result is not None
        assert result[0] == "event_001"

    def test_find_closest_event_between_events(
        self, sample_events_mapping: dict[str, list[Any]], sample_events_columns: list[str]
    ):
        """Test finding closest event when target is between two events."""
        session_start_time_str = "2025-03-31T18:40:32.302000+00:00"

        # Target at 10s - event_001 is at ~3s, event_002 is at ~18s
        # Should return event_001 as it's closer
        result = _find_closest_event(
            target_ms=10000,
            simplified_events_mapping=sample_events_mapping,
            simplified_events_columns=sample_events_columns,
            session_start_time_str=session_start_time_str,
        )

        assert result is not None
        # event_001 at ~3s is closer to 10s than event_002 at ~18s
        assert result[0] == "event_001"

    def test_find_closest_event_empty_mapping(self, sample_events_columns: list[str]):
        """Test with empty events mapping."""
        session_start_time_str = "2025-03-31T18:40:32.302000+00:00"

        result = _find_closest_event(
            target_ms=10000,
            simplified_events_mapping={},
            simplified_events_columns=sample_events_columns,
            session_start_time_str=session_start_time_str,
        )

        assert result is None


class TestStoreVideoSessionSummaryActivity:
    @pytest.fixture
    def mock_llm_input(self, mock_video_session_id: str) -> SingleSessionSummaryLlmInputs:
        """Create a mock SingleSessionSummaryLlmInputs for testing."""
        return SingleSessionSummaryLlmInputs(
            session_id=mock_video_session_id,
            user_id=1,
            user_distinct_id_to_log="test_distinct_id",
            summary_prompt="Test summary prompt",
            system_prompt="Test system prompt",
            simplified_events_mapping={
                "event_001": [
                    "event_001",
                    0,
                    "$pageview",
                    "2025-03-31T18:40:35.000000+00:00",
                    "click",
                    "url_1",
                    "window_1",
                    None,
                    None,
                ],
                "event_002": [
                    "event_002",
                    1,
                    "$autocapture",
                    "2025-03-31T18:40:50.000000+00:00",
                    "click",
                    "url_1",
                    "window_1",
                    None,
                    None,
                ],
            },
            simplified_events_columns=[
                "event_id",
                "event_index",
                "event",
                "timestamp",
                "$event_type",
                "$current_url",
                "$window_id",
                "$exception_types",
                "$exception_values",
            ],
            event_ids_mapping={
                "event_001": f"{mock_video_session_id}_uuid_001",
                "event_002": f"{mock_video_session_id}_uuid_002",
            },
            url_mapping_reversed={
                "url_1": "https://app.posthog.com/dashboard",
                "url_2": "https://app.posthog.com/insights",
            },
            window_mapping_reversed={"window_1": "main-window-id"},
            session_start_time_str="2025-03-31T18:40:32.302000+00:00",
            session_duration=120,
            distinct_id="test_distinct_id",
            model_to_use="gemini-2.5-pro-preview-05-06",
        )

    @pytest.mark.asyncio
    async def test_store_summary_creates_with_visual_confirmation(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_consolidated_video_analysis: ConsolidatedVideoAnalysis,
        mock_llm_input: SingleSessionSummaryLlmInputs,
    ):
        """Test that summary is stored with visual_confirmation=True."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        compressed_llm_input = _compress_redis_data(json.dumps(dataclasses.asdict(mock_llm_input)))
        mock_redis_client = MagicMock()
        mock_redis_client.get = AsyncMock(return_value=compressed_llm_input)

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a6_store_video_session_summary.get_redis_state_client",
                return_value=(mock_redis_client, "input_key", None),
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a6_store_video_session_summary.get_data_class_from_redis",
                return_value=mock_llm_input,
            ),
        ):
            await store_video_session_summary_activity(
                inputs=inputs,
                analysis=mock_consolidated_video_analysis,
            )

            # Verify summary was created
            summary = await SingleSessionSummary.objects.aget(
                team_id=ateam.id,
                session_id=mock_video_session_id,
            )

            assert summary is not None
            assert summary.run_metadata is not None
            assert summary.run_metadata["visual_confirmation"] is True

            # Cleanup
            await summary.adelete()

    @pytest.mark.asyncio
    async def test_store_summary_skips_existing(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_consolidated_video_analysis: ConsolidatedVideoAnalysis,
    ):
        """Test that existing summary is not overwritten."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        # Create existing summary
        existing_summary = await SingleSessionSummary.objects.acreate(
            team_id=ateam.id,
            session_id=mock_video_session_id,
            summary={
                "segments": [],
                "key_actions": [],
                "segment_outcomes": [],
                "session_outcome": {"success": True, "description": "Existing summary"},
            },
            run_metadata={"model_used": "test", "visual_confirmation": False},
            created_by_id=auser.id,
        )

        try:
            await store_video_session_summary_activity(
                inputs=inputs,
                analysis=mock_consolidated_video_analysis,
            )

            # Summary should remain unchanged
            summary = await SingleSessionSummary.objects.aget(id=existing_summary.id)
            assert summary.run_metadata is not None
            assert summary.run_metadata["visual_confirmation"] is False  # Still the old value
        finally:
            await existing_summary.adelete()

    @pytest.mark.asyncio
    async def test_store_summary_maps_timestamps_to_events(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_consolidated_video_analysis: ConsolidatedVideoAnalysis,
        mock_llm_input: SingleSessionSummaryLlmInputs,
    ):
        """Test that video timestamps are mapped to real event IDs."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a6_store_video_session_summary.get_redis_state_client",
                return_value=(MagicMock(), "input_key", None),
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a6_store_video_session_summary.get_data_class_from_redis",
                return_value=mock_llm_input,
            ),
        ):
            await store_video_session_summary_activity(
                inputs=inputs,
                analysis=mock_consolidated_video_analysis,
            )

            summary = await SingleSessionSummary.objects.aget(
                team_id=ateam.id,
                session_id=mock_video_session_id,
            )

            # Verify segments have event IDs
            segments = summary.summary["segments"]
            assert len(segments) > 0

            # First segment should have start/end event IDs
            first_segment = segments[0]
            assert "start_event_id" in first_segment
            assert "end_event_id" in first_segment

            # Cleanup
            await summary.adelete()

    @pytest.mark.asyncio
    async def test_store_summary_no_llm_input_raises_error(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_consolidated_video_analysis: ConsolidatedVideoAnalysis,
    ):
        """Test that missing LLM input raises ValueError."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a6_store_video_session_summary.get_redis_state_client",
                return_value=(MagicMock(), "input_key", None),
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a6_store_video_session_summary.get_data_class_from_redis",
                return_value=None,  # No LLM input
            ),
        ):
            with pytest.raises(ValueError, match="No LLM input found"):
                await store_video_session_summary_activity(
                    inputs=inputs,
                    analysis=mock_consolidated_video_analysis,
                )

    @pytest.mark.asyncio
    async def test_store_summary_includes_segment_outcomes(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_summary_inputs_factory: Callable,
        mock_consolidated_video_analysis: ConsolidatedVideoAnalysis,
        mock_llm_input: SingleSessionSummaryLlmInputs,
    ):
        """Test that segment outcomes from video analysis are included."""
        inputs = mock_video_summary_inputs_factory(mock_video_session_id, ateam.id, auser.id)

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a6_store_video_session_summary.get_redis_state_client",
                return_value=(MagicMock(), "input_key", None),
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a6_store_video_session_summary.get_data_class_from_redis",
                return_value=mock_llm_input,
            ),
        ):
            await store_video_session_summary_activity(
                inputs=inputs,
                analysis=mock_consolidated_video_analysis,
            )

            summary = await SingleSessionSummary.objects.aget(
                team_id=ateam.id,
                session_id=mock_video_session_id,
            )

            # Verify segment outcomes are present
            segment_outcomes = summary.summary["segment_outcomes"]
            assert len(segment_outcomes) == len(mock_consolidated_video_analysis.segment_outcomes)

            # Verify session outcome
            session_outcome = summary.summary["session_outcome"]
            assert session_outcome["success"] == mock_consolidated_video_analysis.session_outcome.success

            # Cleanup
            await summary.adelete()
