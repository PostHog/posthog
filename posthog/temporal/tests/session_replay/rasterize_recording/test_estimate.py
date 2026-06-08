from parameterized import parameterized

from posthog.temporal.session_replay.rasterize_recording.estimate import (
    RASTERIZE_ACTIVITY_TIMEOUT_S,
    apply_skip_inactivity_timeout_guard,
    clip_duration_s,
    estimate_rasterize_wall_time_s,
)


class TestClipDurationS:
    @parameterized.expand(
        [
            ("offsets", 10.0, 40.0, None, 30.0),
            ("duration_only", None, None, 45.0, 45.0),
            ("end_from_duration", 5.0, 35.0, 30.0, 30.0),
        ]
    )
    def test_clip_duration_s(
        self, _name: str, start: float | None, end: float | None, duration: float | None, expected: float
    ) -> None:
        assert clip_duration_s(start_offset_s=start, end_offset_s=end, duration=duration) == expected


class TestEstimateRasterizeWallTimeS:
    def test_scales_with_duration_and_fps(self) -> None:
        assert estimate_rasterize_wall_time_s(content_duration_s=3815, recording_fps=24) == 3815 * 24 / 30


class TestApplySkipInactivityTimeoutGuard:
    @parameterized.expand(
        [
            ("already_skipping", {"skip_inactivity": True, "duration": 3815}, 3815, 570, False),
            ("short_clip", {"skip_inactivity": False, "duration": 30}, 30, 20, False),
            (
                "long_full_session",
                {"skip_inactivity": False, "duration": 3815, "recording_fps": 24},
                3815,
                570,
                True,
            ),
        ]
    )
    def test_apply_skip_inactivity_timeout_guard(
        self,
        _name: str,
        export_context: dict,
        session_duration_s: float,
        active_seconds_s: float,
        should_adjust: bool,
    ) -> None:
        skip_inactivity, patches = apply_skip_inactivity_timeout_guard(
            export_context,
            session_duration_s=session_duration_s,
            active_seconds_s=active_seconds_s,
        )

        if should_adjust:
            assert skip_inactivity is True
            assert patches["skip_inactivity"] is True
            assert patches["skip_inactivity_auto_adjusted"] is True
            assert patches["skip_inactivity_adjustment_message"]
        else:
            assert patches == {}

    def test_long_active_session_gets_stronger_warning(self) -> None:
        active_duration_s = (RASTERIZE_ACTIVITY_TIMEOUT_S * 30 / 24) + 60
        _, patches = apply_skip_inactivity_timeout_guard(
            {"skip_inactivity": False},
            session_duration_s=active_duration_s,
            active_seconds_s=active_duration_s,
        )
        assert patches
        assert "may still time out" in str(patches["skip_inactivity_adjustment_message"])
