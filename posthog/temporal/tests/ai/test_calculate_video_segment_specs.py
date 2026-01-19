import pytest

from posthog.schema import ReplayInactivityPeriod

from posthog.temporal.ai.session_summary.summarize_session import (
    SESSION_VIDEO_CHUNK_DURATION_S,
    calculate_video_segment_specs,
)
from posthog.temporal.ai.session_summary.types.video import VideoSegmentSpec

from ee.hogai.session_summaries.constants import SESSION_VIDEO_RENDERING_DELAY


class TestCalculateVideoSegmentSpecsWithoutInactivityData:
    """Tests for uniform chunk splitting when no inactivity data is available."""

    @pytest.mark.parametrize(
        "video_duration,chunk_duration,rendering_delay,expected_segments",
        [
            # Standard case: 130s video split into 2 segments
            (
                130,
                SESSION_VIDEO_CHUNK_DURATION_S,
                SESSION_VIDEO_RENDERING_DELAY,
                [
                    VideoSegmentSpec(segment_index=0, start_time=SESSION_VIDEO_RENDERING_DELAY, end_time=60),
                    VideoSegmentSpec(segment_index=1, start_time=60, end_time=130),
                ],
            ),
            # Short video: less than chunk_duration, should still produce 1 segment
            (
                30,
                SESSION_VIDEO_CHUNK_DURATION_S,
                SESSION_VIDEO_RENDERING_DELAY,
                [
                    VideoSegmentSpec(segment_index=0, start_time=SESSION_VIDEO_RENDERING_DELAY, end_time=30),
                ],
            ),
        ],
        ids=["standard_video_two_segments", "short_video_single_segment"],
    )
    def test_uniform_splitting_without_inactivity_data(
        self,
        video_duration: float,
        chunk_duration: float,
        rendering_delay: float,
        expected_segments: list[VideoSegmentSpec],
    ):
        result = calculate_video_segment_specs(
            video_duration=video_duration,
            chunk_duration=chunk_duration,
            rendering_delay=rendering_delay,
            inactivity_periods=None,
        )

        assert result == expected_segments


class TestCalculateVideoSegmentSpecsWithInactivityData:
    """Tests for activity-based splitting when inactivity data is available."""

    @pytest.mark.parametrize(
        "video_duration,chunk_duration,rendering_delay,inactivity_periods,expected_segments",
        [
            # Single active period smaller than chunk_duration
            (
                100,
                SESSION_VIDEO_CHUNK_DURATION_S,
                SESSION_VIDEO_RENDERING_DELAY,
                [
                    ReplayInactivityPeriod(active=True, ts_from_s=10, ts_to_s=50),
                    ReplayInactivityPeriod(active=False, ts_from_s=50, ts_to_s=100),
                ],
                [
                    VideoSegmentSpec(segment_index=0, start_time=10, end_time=50),
                ],
            ),
            # Large active period split into chunks, avoiding tiny leftover
            (
                200,
                SESSION_VIDEO_CHUNK_DURATION_S,
                SESSION_VIDEO_RENDERING_DELAY,
                [
                    ReplayInactivityPeriod(active=False, ts_from_s=0, ts_to_s=10),
                    ReplayInactivityPeriod(active=True, ts_from_s=10, ts_to_s=150),
                    ReplayInactivityPeriod(active=False, ts_from_s=150, ts_to_s=200),
                ],
                [
                    # First chunk: 60s
                    VideoSegmentSpec(segment_index=0, start_time=10, end_time=70),
                    # Second chunk: extends to end (80s) to avoid tiny 20s leftover
                    VideoSegmentSpec(segment_index=1, start_time=70, end_time=150),
                ],
            ),
        ],
        ids=["single_small_active_period", "large_active_period_avoids_tiny_chunk"],
    )
    def test_activity_based_splitting_with_inactivity_data(
        self,
        video_duration: float,
        chunk_duration: float,
        rendering_delay: float,
        inactivity_periods: list[ReplayInactivityPeriod],
        expected_segments: list[VideoSegmentSpec],
    ):
        result = calculate_video_segment_specs(
            video_duration=video_duration,
            chunk_duration=chunk_duration,
            rendering_delay=rendering_delay,
            inactivity_periods=inactivity_periods,
        )

        assert result == expected_segments
