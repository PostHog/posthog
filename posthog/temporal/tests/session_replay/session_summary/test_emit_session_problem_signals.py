import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.temporal.session_replay.session_summary.activities.a6a_emit_session_problem_signals import (
    MIN_MOMENT_PREVIEW_DURATION_S,
    _classify_problem,
    _parse_timestamp_to_seconds,
    _rasterize_moment_preview,
)
from posthog.temporal.session_replay.session_summary.types.video import ConsolidatedVideoSegment


def _make_segment(**kwargs) -> ConsolidatedVideoSegment:
    defaults = {
        "title": "Test segment",
        "start_time": "00:00",
        "end_time": "01:00",
        "description": "Test",
        "success": True,
        "exception": None,
        "confusion_detected": False,
        "abandonment_detected": False,
    }
    defaults.update(kwargs)
    return ConsolidatedVideoSegment(**defaults)


class TestClassifyProblem:
    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({"exception": "blocking"}, "blocking_exception"),
            ({"abandonment_detected": True}, "abandonment"),
            ({"exception": "non-blocking"}, "non_blocking_exception"),
            ({"confusion_detected": True}, "confusion"),
            ({"success": False}, "failure"),
            ({}, None),
        ],
        ids=["blocking", "abandonment", "non_blocking", "confusion", "failure", "no_problem"],
    )
    def test_single_flag(self, kwargs, expected):
        assert _classify_problem(_make_segment(**kwargs)) == expected

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            (
                {"exception": "blocking", "abandonment_detected": True, "confusion_detected": True, "success": False},
                "blocking_exception",
            ),
            (
                {
                    "abandonment_detected": True,
                    "exception": "non-blocking",
                    "confusion_detected": True,
                    "success": False,
                },
                "abandonment",
            ),
            ({"exception": "non-blocking", "confusion_detected": True, "success": False}, "non_blocking_exception"),
            ({"confusion_detected": True, "success": False}, "confusion"),
        ],
        ids=["blocking_wins_all", "abandonment_wins_lower", "non_blocking_wins_lower", "confusion_wins_failure"],
    )
    def test_priority_ordering(self, kwargs, expected):
        assert _classify_problem(_make_segment(**kwargs)) == expected


class TestParseTimestampToSeconds:
    @pytest.mark.parametrize(
        "ts, expected",
        [
            ("00:00", 0.0),
            ("01:30", 90.0),
            ("10:05", 605.0),
            ("1:00:00", 3600.0),
            ("1:30:45", 5445.0),
            ("0:00:30", 30.0),
        ],
        ids=["zero", "ninety_seconds", "ten_five", "one_hour", "ninety_min_45s", "thirty_seconds"],
    )
    def test_parses_correctly(self, ts, expected):
        assert _parse_timestamp_to_seconds(ts) == expected


_RASTERIZE_PATCH_OBJECTS = (
    "posthog.temporal.session_replay.session_summary.activities.a6a_emit_session_problem_signals.ExportedAsset.objects"
)
_RASTERIZE_PATCH_CONNECT = (
    "posthog.temporal.session_replay.session_summary.activities.a6a_emit_session_problem_signals.async_connect"
)


@pytest.mark.django_db
class TestRasterizeMomentPreview:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "session_id, start_time_s, end_time_s, expected_start, expected_end",
        [
            # Segment already >= minimum duration — no expansion
            ("sess-long", 60.0, 120.0, 60.0, 120.0),
            # Short segment at midpoint — expand symmetrically (midpoint=55, half=15)
            ("sess-short", 50.0, 60.0, 40.0, 70.0),
            # Segment near start (5–10s) — start clamped to 0, end extended to minimum
            ("sess-early", 5.0, 10.0, 0, MIN_MOMENT_PREVIEW_DURATION_S),
        ],
        ids=["no_expansion", "symmetric_expansion", "clamp_start_extend_end"],
    )
    async def test_export_context_offsets(
        self,
        session_id: str,
        start_time_s: float,
        end_time_s: float,
        expected_start: float,
        expected_end: float,
    ):
        mock_asset = MagicMock()
        mock_asset.id = 42
        mock_client = AsyncMock()
        mock_client.execute_workflow = AsyncMock(return_value=None)

        with (
            patch(_RASTERIZE_PATCH_OBJECTS) as mock_objects,
            patch(_RASTERIZE_PATCH_CONNECT, return_value=mock_client),
        ):
            mock_objects.acreate = AsyncMock(return_value=mock_asset)
            result = await _rasterize_moment_preview(
                team_id=1,
                session_id=session_id,
                start_time_s=start_time_s,
                end_time_s=end_time_s,
            )

        assert result == 42
        ctx = mock_objects.acreate.call_args[1]["export_context"]
        assert ctx["session_recording_id"] == session_id
        assert ctx["start_offset_s"] == expected_start
        assert ctx["end_offset_s"] == expected_end
        assert ctx["end_offset_s"] - ctx["start_offset_s"] >= MIN_MOMENT_PREVIEW_DURATION_S
        assert ctx["playback_speed"] == 1
        mock_client.execute_workflow.assert_called_once()
        assert mock_client.execute_workflow.call_args[0][0] == "rasterize-recording"

    @pytest.mark.asyncio
    async def test_returns_none_and_cleans_up_on_workflow_failure(self):
        mock_asset = MagicMock()
        mock_asset.id = 50
        mock_client = AsyncMock()
        mock_client.execute_workflow = AsyncMock(side_effect=RuntimeError("workflow failed"))
        mock_filter = AsyncMock()

        with (
            patch(_RASTERIZE_PATCH_OBJECTS) as mock_objects,
            patch(_RASTERIZE_PATCH_CONNECT, return_value=mock_client),
        ):
            mock_objects.acreate = AsyncMock(return_value=mock_asset)
            mock_objects.filter = MagicMock(return_value=mock_filter)
            mock_filter.adelete = AsyncMock(return_value=None)

            result = await _rasterize_moment_preview(
                team_id=1,
                session_id="sess-fail",
                start_time_s=0.0,
                end_time_s=60.0,
            )

        assert result is None
        mock_objects.filter.assert_called_once_with(id=50)
        mock_filter.adelete.assert_called_once()
