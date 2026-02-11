import pytest

from posthog.schema import ReplayInactivityPeriod

from posthog.temporal.ai.session_summary.summarize_session import (
    SESSION_VIDEO_CHUNK_DURATION_S,
    calculate_video_segment_specs,
)
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.ai.session_summary.types.video import VideoSegmentSpec

DUMMY_INPUTS = SingleSessionSummaryInputs(
    session_id="test-session",
    user_id=1,
    team_id=1,
    redis_key_base="test",
    model_to_use="test",
)


class TestCalculateVideoSegmentSpecsRequiresInactivityData:
    @pytest.mark.parametrize(
        "inactivity_periods",
        [None, []],
        ids=["none", "empty_list"],
    )
    def test_raises_without_inactivity_data(self, inactivity_periods):
        with pytest.raises(ValueError, match="Inactivity periods were not provided"):
            calculate_video_segment_specs(
                video_duration=100,
                chunk_duration=SESSION_VIDEO_CHUNK_DURATION_S,
                inputs=DUMMY_INPUTS,
                inactivity_periods=inactivity_periods,
            )


class TestCalculateVideoSegmentSpecsValidation:
    @pytest.mark.parametrize(
        "video_duration,inactivity_periods,error_match",
        [
            (
                100,
                [
                    ReplayInactivityPeriod(active=True, ts_from_s=10, ts_to_s=None, recording_ts_from_s=10),
                    ReplayInactivityPeriod(
                        active=True, ts_from_s=50, ts_to_s=80, recording_ts_from_s=50, recording_ts_to_s=80
                    ),
                ],
                "has no ts_to_s",
            ),
            (
                100,
                [
                    ReplayInactivityPeriod(
                        active=True, ts_from_s=10, ts_to_s=50, recording_ts_from_s=50, recording_ts_to_s=10
                    ),
                ],
                "Invalid recording period time range",
            ),
            (
                100,
                [
                    ReplayInactivityPeriod(
                        active=True, ts_from_s=50, ts_to_s=10, recording_ts_from_s=10, recording_ts_to_s=50
                    ),
                ],
                "Invalid session period time range",
            ),
        ],
        ids=[
            "non_last_period_missing_ts_to",
            "invalid_recording_time_range",
            "invalid_session_time_range",
        ],
    )
    def test_validation_errors(
        self,
        video_duration: float,
        inactivity_periods: list[ReplayInactivityPeriod],
        error_match: str,
    ):
        with pytest.raises(ValueError, match=error_match):
            calculate_video_segment_specs(
                video_duration=video_duration,
                chunk_duration=SESSION_VIDEO_CHUNK_DURATION_S,
                inputs=DUMMY_INPUTS,
                inactivity_periods=inactivity_periods,
            )


class TestCalculateVideoSegmentSpecsWithInactivityData:
    @pytest.mark.parametrize(
        "video_duration,chunk_duration,inactivity_periods,expected_segments",
        [
            # Single active period smaller than chunk_duration
            (
                100,
                SESSION_VIDEO_CHUNK_DURATION_S,
                [
                    ReplayInactivityPeriod(
                        active=True, ts_from_s=10, ts_to_s=50, recording_ts_from_s=10, recording_ts_to_s=50
                    ),
                    ReplayInactivityPeriod(active=False, ts_from_s=50, ts_to_s=100),
                ],
                [
                    VideoSegmentSpec(
                        segment_index=0, start_time=10, end_time=50, recording_start_time=10, recording_end_time=50
                    ),
                ],
            ),
            # Large active period split into chunks, extending last chunk to avoid tiny leftover
            (
                200,
                SESSION_VIDEO_CHUNK_DURATION_S,
                [
                    ReplayInactivityPeriod(active=False, ts_from_s=0, ts_to_s=10),
                    ReplayInactivityPeriod(
                        active=True, ts_from_s=10, ts_to_s=150, recording_ts_from_s=10, recording_ts_to_s=150
                    ),
                    ReplayInactivityPeriod(active=False, ts_from_s=150, ts_to_s=200),
                ],
                [
                    VideoSegmentSpec(
                        segment_index=0, start_time=10, end_time=70, recording_start_time=10, recording_end_time=70
                    ),
                    VideoSegmentSpec(
                        segment_index=1, start_time=70, end_time=150, recording_start_time=70, recording_end_time=150
                    ),
                ],
            ),
            # Multiple active periods with inactive gap — recording timestamps differ from session timestamps
            (
                70,
                SESSION_VIDEO_CHUNK_DURATION_S,
                [
                    ReplayInactivityPeriod(
                        active=True, ts_from_s=0, ts_to_s=30, recording_ts_from_s=0, recording_ts_to_s=30
                    ),
                    ReplayInactivityPeriod(active=False, ts_from_s=30, ts_to_s=80),
                    ReplayInactivityPeriod(
                        active=True, ts_from_s=80, ts_to_s=120, recording_ts_from_s=30, recording_ts_to_s=70
                    ),
                ],
                [
                    VideoSegmentSpec(
                        segment_index=0, start_time=0, end_time=30, recording_start_time=0, recording_end_time=30
                    ),
                    VideoSegmentSpec(
                        segment_index=1, start_time=80, end_time=120, recording_start_time=30, recording_end_time=70
                    ),
                ],
            ),
            # Last active period with ts_to_s=None infers end from video_duration
            (
                50,
                SESSION_VIDEO_CHUNK_DURATION_S,
                [
                    ReplayInactivityPeriod(active=True, ts_from_s=10, ts_to_s=None, recording_ts_from_s=10),
                ],
                [
                    VideoSegmentSpec(
                        segment_index=0, start_time=10, end_time=50, recording_start_time=10, recording_end_time=50
                    ),
                ],
            ),
            # Active period without recording_ts_from_s is skipped
            (
                100,
                SESSION_VIDEO_CHUNK_DURATION_S,
                [
                    ReplayInactivityPeriod(active=True, ts_from_s=0, ts_to_s=30),
                    ReplayInactivityPeriod(
                        active=True, ts_from_s=30, ts_to_s=60, recording_ts_from_s=30, recording_ts_to_s=60
                    ),
                    ReplayInactivityPeriod(active=False, ts_from_s=60, ts_to_s=100),
                ],
                [
                    VideoSegmentSpec(
                        segment_index=0, start_time=30, end_time=60, recording_start_time=30, recording_end_time=60
                    ),
                ],
            ),
        ],
        ids=[
            "single_small_active_period",
            "large_active_period_avoids_tiny_chunk",
            "multiple_active_periods_with_recording_offset",
            "last_period_infers_end_from_video_duration",
            "skips_period_without_recording_start",
        ],
    )
    def test_activity_based_splitting(
        self,
        video_duration: float,
        chunk_duration: float,
        inactivity_periods: list[ReplayInactivityPeriod],
        expected_segments: list[VideoSegmentSpec],
    ):
        result = calculate_video_segment_specs(
            video_duration=video_duration,
            chunk_duration=chunk_duration,
            inputs=DUMMY_INPUTS,
            inactivity_periods=inactivity_periods,
        )

        assert result == expected_segments
