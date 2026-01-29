"""
Tests for Activity 3: analyze_video_segment_activity

This activity analyzes a segment of the uploaded video with Gemini using video_metadata.
"""

from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.models import Team
from posthog.models.user import User
from posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment import (
    _find_events_in_time_range,
    _format_timestamp_as_mm_ss,
    analyze_video_segment_activity,
)
from posthog.temporal.ai.session_summary.activities.tests.conftest import create_video_summary_inputs
from posthog.temporal.ai.session_summary.types.video import UploadedVideo, VideoSegmentSpec

pytestmark = pytest.mark.django_db


class TestFormatTimestampAsMmSs:
    """Unit tests for _format_timestamp_as_mm_ss helper function."""

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "00:00"),
            (65, "01:05"),
            (3661, "61:01"),
        ],
        ids=["zero", "mixed_minutes_seconds", "over_an_hour"],
    )
    def test_format_timestamp_as_mm_ss(self, seconds: float, expected: str):
        """
        Boundary cases for timestamp formatting: zero, typical, and overflow values.

        The function must handle edge cases like 0 and values exceeding 60 minutes.
        """
        assert _format_timestamp_as_mm_ss(seconds) == expected


class TestFindEventsInTimeRange:
    """Unit tests for _find_events_in_time_range helper function."""

    @pytest.fixture
    def sample_events_mapping(self) -> dict[str, list[Any]]:
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
                "2025-03-31T18:40:45.000000+00:00",
                "click",
                "url_1",
                "window_1",
            ],
            "event_003": [
                "event_003",
                2,
                "$autocapture",
                "2025-03-31T18:40:55.000000+00:00",
                "submit",
                "url_2",
                "window_1",
            ],
            "event_004": [
                "event_004",
                3,
                "$pageview",
                "2025-03-31T18:41:05.000000+00:00",
                None,
                "url_2",
                "window_1",
            ],
        }

    @pytest.fixture
    def sample_events_columns(self) -> list[str]:
        return [
            "event_id",
            "event_index",
            "event",
            "timestamp",
            "$event_type",
            "$current_url",
            "$window_id",
        ]

    def test_find_events_in_range_returns_matching_events(
        self,
        sample_events_mapping: dict[str, list[Any]],
        sample_events_columns: list[str],
    ):
        """
        Core filtering: returns only events within the specified time range.

        This is the primary contract of the function - filter by time boundaries.
        """
        session_start_time_str = "2025-03-31T18:40:32.302000+00:00"

        # Time range: 10s to 25s from session start
        # Event 002 is at ~13s (18:40:45 - 18:40:32.302)
        # Event 003 is at ~23s (18:40:55 - 18:40:32.302)
        result = _find_events_in_time_range(
            start_ms=10000,
            end_ms=25000,
            simplified_events_mapping=sample_events_mapping,
            simplified_events_columns=sample_events_columns,
            session_start_time_str=session_start_time_str,
        )

        event_ids = [event_id for event_id, _ in result]
        assert "event_002" in event_ids
        assert "event_003" in event_ids
        assert "event_001" not in event_ids  # Too early
        assert "event_004" not in event_ids  # Too late

    def test_find_events_in_range_empty_when_no_matches(
        self,
        sample_events_mapping: dict[str, list[Any]],
        sample_events_columns: list[str],
    ):
        """
        Empty result case: returns empty list when no events match time range.

        Important edge case to ensure we handle missing data gracefully.
        """
        session_start_time_str = "2025-03-31T18:40:32.302000+00:00"

        result = _find_events_in_time_range(
            start_ms=100000,  # 100s from start
            end_ms=110000,  # 110s from start
            simplified_events_mapping=sample_events_mapping,
            simplified_events_columns=sample_events_columns,
            session_start_time_str=session_start_time_str,
        )

        assert len(result) == 0


class TestAnalyzeVideoSegmentActivity:
    @pytest.mark.asyncio
    async def test_analyze_video_segment_basic_flow(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_uploaded_video: UploadedVideo,
        mock_gemini_generate_response: MagicMock,
    ):
        """
        Happy path: video segment analysis returns parsed segments from LLM.

        Verifies the complete flow: call LLM, parse response, return structured output.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)
        segment = VideoSegmentSpec(segment_index=0, start_time=0.0, end_time=15.0)

        mock_client = MagicMock()
        mock_client.models.generate_content = AsyncMock(return_value=mock_gemini_generate_response)

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment.genai.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment.get_redis_state_client"
            ) as mock_redis_state,
            patch(
                "posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment.get_data_class_from_redis",
                return_value=None,
            ),
        ):
            mock_redis_state.return_value = (MagicMock(), "input_key", None)

            result = await analyze_video_segment_activity(
                inputs=inputs,
                uploaded_video=mock_uploaded_video,
                segment=segment,
                trace_id="test-trace-id",
                team_name=ateam.name,
            )

            # Should return parsed segments from LLM response
            assert len(result) == 3
            assert result[0].start_time == "00:00"
            assert result[0].end_time == "00:05"
            assert "dashboard" in result[0].description.lower()

            mock_client.models.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_video_segment_with_correlated_events(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_uploaded_video: UploadedVideo,
        mock_gemini_generate_response: MagicMock,
    ):
        """
        Event correlation: tracked events are included in LLM prompt for context.

        This is a core feature - the LLM needs event context to understand what happened.
        """
        from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs

        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)
        segment = VideoSegmentSpec(segment_index=0, start_time=0.0, end_time=15.0)

        # Create mock LLM input with events that fall within the segment time range
        mock_llm_input = SingleSessionSummaryLlmInputs(
            session_id=mock_video_session_id,
            user_id=auser.id,
            summary_prompt="Test prompt",
            system_prompt="Test system prompt",
            simplified_events_mapping={
                "event_001": [
                    "event_001",
                    0,
                    "$pageview",
                    "2025-03-31T18:40:35.000000+00:00",  # ~3s from start
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
                    "2025-03-31T18:40:42.000000+00:00",  # ~10s from start
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
            url_mapping_reversed={"url_1": "https://app.posthog.com/dashboard"},
            window_mapping_reversed={"window_1": "main-window-id"},
            session_start_time_str="2025-03-31T18:40:32.302000+00:00",
            session_duration=120,
            distinct_id="test_distinct_id",
            model_to_use="gemini-2.5-pro-preview-05-06",
        )

        mock_client = MagicMock()
        mock_client.models.generate_content = AsyncMock(return_value=mock_gemini_generate_response)

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment.genai.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment.get_redis_state_client"
            ) as mock_redis_state,
            patch(
                "posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment.get_data_class_from_redis",
                return_value=mock_llm_input,
            ),
        ):
            mock_redis_state.return_value = (MagicMock(), "input_key", None)

            result = await analyze_video_segment_activity(
                inputs=inputs,
                uploaded_video=mock_uploaded_video,
                segment=segment,
                trace_id="test-trace-id",
                team_name=ateam.name,
            )

            assert len(result) == 3

            # Verify that the LLM was called with events context in the prompt
            call_args = mock_client.models.generate_content.call_args
            contents = call_args.kwargs["contents"]
            prompt_text = contents[1]

            assert "<tracked_events>" in prompt_text
            assert "event_001" in prompt_text
            assert "event_002" in prompt_text
            assert "$pageview" in prompt_text
            assert "https://app.posthog.com/dashboard" in prompt_text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("response_text", "response_id"),
        [
            ("The user did some things but I can't describe them properly.", "malformed"),
            (None, "empty"),
        ],
        ids=["malformed", "empty"],
    )
    async def test_analyze_video_segment_handles_invalid_llm_responses(
        self,
        response_text: str | None,
        response_id: str,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_uploaded_video: UploadedVideo,
    ):
        """
        Error resilience: malformed or empty LLM responses return empty list.

        The LLM might fail to follow the expected format, and we need to handle that gracefully.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)
        segment = VideoSegmentSpec(segment_index=0, start_time=0.0, end_time=15.0)

        mock_response = MagicMock()
        mock_response.text = response_text

        mock_client = MagicMock()
        mock_client.models.generate_content = AsyncMock(return_value=mock_response)

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment.genai.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment.get_redis_state_client"
            ) as mock_redis_state,
            patch(
                "posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment.get_data_class_from_redis",
                return_value=None,
            ),
        ):
            mock_redis_state.return_value = (MagicMock(), "input_key", None)

            result = await analyze_video_segment_activity(
                inputs=inputs,
                uploaded_video=mock_uploaded_video,
                segment=segment,
                trace_id="test-trace-id",
                team_name=ateam.name,
            )

            assert len(result) == 0
