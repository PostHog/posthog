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
            (5, "00:05"),
            (30, "00:30"),
            (60, "01:00"),
            (65, "01:05"),
            (90, "01:30"),
            (120, "02:00"),
            (3600, "60:00"),
            (3661, "61:01"),
        ],
    )
    def test_format_timestamp_as_mm_ss(self, seconds: float, expected: str):
        """Test various timestamp conversions."""
        assert _format_timestamp_as_mm_ss(seconds) == expected


class TestFindEventsInTimeRange:
    """Unit tests for _find_events_in_time_range helper function."""

    @pytest.fixture
    def sample_events_mapping(self) -> dict[str, list[Any]]:
        """Sample events mapping for testing."""
        return {
            "event_001": [
                "event_001",  # event_id
                0,  # event_index
                "$pageview",  # event
                "2025-03-31T18:40:35.000000+00:00",  # timestamp
                "click",  # $event_type
                "url_1",  # $current_url
                "window_1",  # $window_id
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
        """Sample events columns for testing."""
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
        """Test finding events within a time range."""
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

        # Should return events 002 and 003
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
        """Test returns empty list when no events match time range."""
        session_start_time_str = "2025-03-31T18:40:32.302000+00:00"

        # Time range where no events exist
        result = _find_events_in_time_range(
            start_ms=100000,  # 100s from start
            end_ms=110000,  # 110s from start
            simplified_events_mapping=sample_events_mapping,
            simplified_events_columns=sample_events_columns,
            session_start_time_str=session_start_time_str,
        )

        assert len(result) == 0

    def test_find_events_in_range_sorted_by_event_index(
        self,
        sample_events_mapping: dict[str, list[Any]],
        sample_events_columns: list[str],
    ):
        """Test that returned events are sorted by event_index."""
        session_start_time_str = "2025-03-31T18:40:32.302000+00:00"

        # Get all events
        result = _find_events_in_time_range(
            start_ms=0,
            end_ms=100000,
            simplified_events_mapping=sample_events_mapping,
            simplified_events_columns=sample_events_columns,
            session_start_time_str=session_start_time_str,
        )

        event_indices = [data[1] for _, data in result]  # event_index is at position 1
        assert event_indices == sorted(event_indices)


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
        """Test basic video segment analysis without cached event data."""
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
                return_value=None,  # No cached data for this test
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
    async def test_analyze_video_segment_no_events_in_range(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_uploaded_video: UploadedVideo,
        mock_gemini_generate_response: MagicMock,
    ):
        """Test analysis when no events fall within segment time range."""
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)
        segment = VideoSegmentSpec(segment_index=5, start_time=75.0, end_time=90.0)

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

            # Should still return segments from LLM even without event context
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_analyze_video_segment_with_correlated_events(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_uploaded_video: UploadedVideo,
        mock_gemini_generate_response: MagicMock,
    ):
        """Test video segment analysis with correlated tracked events from Redis."""
        from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs

        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)
        # Segment from 0-15 seconds
        segment = VideoSegmentSpec(segment_index=0, start_time=0.0, end_time=15.0)

        # Create mock LLM input with events that fall within the segment time range
        # Session starts at 18:40:32.302, segment is 0-15s, so events should be between 18:40:32-18:40:47
        mock_llm_input = SingleSessionSummaryLlmInputs(
            session_id=mock_video_session_id,
            user_id=auser.id,
            summary_prompt="Test prompt",
            system_prompt="Test system prompt",
            simplified_events_mapping={
                "event_001": [
                    "event_001",  # event_id
                    0,  # event_index
                    "$pageview",  # event
                    "2025-03-31T18:40:35.000000+00:00",  # timestamp (~3s from start)
                    "click",  # $event_type
                    "url_1",  # $current_url
                    "window_1",  # $window_id
                    None,  # $exception_types
                    None,  # $exception_values
                ],
                "event_002": [
                    "event_002",
                    1,
                    "$autocapture",
                    "2025-03-31T18:40:42.000000+00:00",  # timestamp (~10s from start)
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

            # Should return parsed segments from LLM response
            assert len(result) == 3

            # Verify that the LLM was called with events context in the prompt
            call_args = mock_client.models.generate_content.call_args
            contents = call_args.kwargs["contents"]
            # The second content item is the prompt text
            prompt_text = contents[1]

            # Verify events were included in prompt
            assert "<tracked_events>" in prompt_text
            assert "event_001" in prompt_text
            assert "event_002" in prompt_text
            assert "$pageview" in prompt_text
            assert "https://app.posthog.com/dashboard" in prompt_text

    @pytest.mark.asyncio
    async def test_analyze_video_segment_parses_timestamps_correctly(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_uploaded_video: UploadedVideo,
    ):
        """Test that MM:SS - MM:SS format is parsed correctly from LLM response."""
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)
        segment = VideoSegmentSpec(segment_index=0, start_time=0.0, end_time=15.0)

        # Custom response with various timestamp formats
        mock_response = MagicMock()
        mock_response.text = """* 00:00 - 00:03: User loaded the page
* 00:03 - 00:08: User clicked login button
* 00:08 - 00:15: User entered credentials"""

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

            assert len(result) == 3
            assert result[0].start_time == "00:00"
            assert result[0].end_time == "00:03"
            assert result[1].start_time == "00:03"
            assert result[1].end_time == "00:08"
            assert result[2].start_time == "00:08"
            assert result[2].end_time == "00:15"

    @pytest.mark.asyncio
    async def test_analyze_video_segment_handles_malformed_response(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_uploaded_video: UploadedVideo,
    ):
        """Test that malformed LLM responses return empty list."""
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)
        segment = VideoSegmentSpec(segment_index=0, start_time=0.0, end_time=15.0)

        # Response without expected format
        mock_response = MagicMock()
        mock_response.text = "The user did some things but I can't describe them properly."

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

            # Should return empty list for malformed response
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_analyze_video_segment_handles_empty_response(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_uploaded_video: UploadedVideo,
    ):
        """Test handling of empty LLM response."""
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)
        segment = VideoSegmentSpec(segment_index=0, start_time=0.0, end_time=15.0)

        mock_response = MagicMock()
        mock_response.text = None

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
