import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.session_replay.rasterize_recording.activities import (
    build_rasterization_input,
    finalize_rasterization,
)
from posthog.temporal.session_replay.rasterize_recording.types import (
    FinalizeRasterizationInput,
    RasterizationActivityOutput,
)

MOCK_SETTINGS = MagicMock()
MOCK_SETTINGS.OBJECT_STORAGE_BUCKET = "posthog"
MOCK_SETTINGS.OBJECT_STORAGE_EXPORTS_FOLDER = "exports"


def _make_asset(
    pk: int = 42,
    team_id: int = 1,
    export_context: dict | None = None,
    export_format: str = "video/mp4",
) -> MagicMock:
    asset = MagicMock()
    asset.pk = pk
    asset.id = pk
    asset.team_id = team_id
    asset.export_context = export_context
    asset.export_format = export_format
    asset.content_location = None
    asset.save = MagicMock()
    return asset


class TestBuildRasterizationInput:
    def test_happy_path(self):
        asset = _make_asset(
            pk=42,
            team_id=7,
            export_context={
                "session_recording_id": "abc123",
                "playback_speed": 8,
                "recording_fps": 30,
                "trim": 60.5,
                "show_metadata_footer": True,
                "width": 1920,
                "height": 1080,
                "start_offset_s": 10.0,
                "end_offset_s": 70.0,
                "skip_inactivity": False,
                "mouse_tail": False,
                "max_virtual_time": 300.0,
            },
        )

        mock_qs = MagicMock()
        mock_qs.select_related.return_value.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            result = build_rasterization_input(42)

        assert result.session_id == "abc123"
        assert result.team_id == 7
        assert result.s3_bucket == "posthog"
        assert result.s3_key_prefix == "exports/mp4/team-7/task-42"
        assert result.playback_speed == 8
        assert result.recording_fps == 30
        assert result.trim == 60.5
        assert result.show_metadata_footer is True
        assert result.viewport_width == 1920
        assert result.viewport_height == 1080
        assert result.start_offset_s == 10.0
        assert result.end_offset_s == 70.0
        assert result.output_format == "mp4"
        assert result.skip_inactivity is False
        assert result.mouse_tail is False
        assert result.max_virtual_time == 300.0

    def test_defaults(self):
        asset = _make_asset(
            pk=10,
            team_id=3,
            export_context={"session_recording_id": "sess-1"},
        )

        mock_qs = MagicMock()
        mock_qs.select_related.return_value.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            result = build_rasterization_input(10)

        assert result.session_id == "sess-1"
        assert result.playback_speed == 4
        assert result.recording_fps == 24
        assert result.trim is None
        assert result.max_virtual_time is None
        assert result.show_metadata_footer is False
        assert result.viewport_width is None
        assert result.viewport_height is None
        assert result.start_offset_s is None
        assert result.end_offset_s is None
        assert result.output_format == "mp4"
        assert result.skip_inactivity is True
        assert result.mouse_tail is True

    def test_missing_session_id_raises(self):
        asset = _make_asset(pk=99, export_context={"playback_speed": 4})

        mock_qs = MagicMock()
        mock_qs.select_related.return_value.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            with pytest.raises(ValueError, match="no session_recording_id"):
                build_rasterization_input(99)

    def test_none_export_context_raises(self):
        asset = _make_asset(pk=100, export_context=None)

        mock_qs = MagicMock()
        mock_qs.select_related.return_value.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            with pytest.raises(ValueError, match="no session_recording_id"):
                build_rasterization_input(100)

    def test_timestamp_and_duration_mapped_to_offsets(self):
        asset = _make_asset(
            pk=50,
            export_context={
                "session_recording_id": "s1",
                "timestamp": 10,
                "duration": 30,
            },
        )

        mock_qs = MagicMock()
        mock_qs.select_related.return_value.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            result = build_rasterization_input(50)

        assert result.start_offset_s == 10
        assert result.end_offset_s == 40

    def test_duration_without_timestamp(self):
        asset = _make_asset(
            pk=50,
            export_context={
                "session_recording_id": "s1",
                "duration": 30,
            },
        )

        mock_qs = MagicMock()
        mock_qs.select_related.return_value.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            result = build_rasterization_input(50)

        assert result.start_offset_s is None
        assert result.end_offset_s == 30

    def test_webm_export_format(self):
        asset = _make_asset(
            pk=50,
            export_format="video/webm",
            export_context={"session_recording_id": "s1"},
        )

        mock_qs = MagicMock()
        mock_qs.select_related.return_value.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            result = build_rasterization_input(50)

        assert result.output_format == "webm"
        assert result.s3_key_prefix == "exports/webm/team-1/task-50"

    def test_gif_export_format(self):
        asset = _make_asset(
            pk=50,
            export_format="image/gif",
            export_context={"session_recording_id": "s1"},
        )

        mock_qs = MagicMock()
        mock_qs.select_related.return_value.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            result = build_rasterization_input(50)

        assert result.output_format == "gif"
        assert result.s3_key_prefix == "exports/gif/team-1/task-50"

    def test_start_offset_zero_not_treated_as_falsy(self):
        asset = _make_asset(
            pk=50,
            export_context={
                "session_recording_id": "s1",
                "start_offset_s": 0,
                "timestamp": 999,
            },
        )

        mock_qs = MagicMock()
        mock_qs.select_related.return_value.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            result = build_rasterization_input(50)

        assert result.start_offset_s == 0

    def test_viewport_dimensions_clamped(self):
        asset = _make_asset(
            pk=50,
            export_context={
                "session_recording_id": "s1",
                "width": 200,
                "height": 5000,
            },
        )

        mock_qs = MagicMock()
        mock_qs.select_related.return_value.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            result = build_rasterization_input(50)

        assert result.viewport_width == 400
        assert result.viewport_height == 2160

    @parameterized.expand(
        [
            ("short_clip_uses_1x", {"session_recording_id": "s1", "duration": 5}, 1),
            ("long_recording_uses_4x", {"session_recording_id": "s1", "duration": 60}, 4),
            ("no_duration_uses_4x", {"session_recording_id": "s1"}, 4),
            ("explicit_speed_overrides", {"session_recording_id": "s1", "duration": 3, "playback_speed": 8}, 8),
        ]
    )
    def test_playback_speed_defaults(self, _name, export_context, expected_speed):
        asset = _make_asset(pk=50, export_context=export_context)

        mock_qs = MagicMock()
        mock_qs.select_related.return_value.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            result = build_rasterization_input(50)

        assert result.playback_speed == expected_speed

    @parameterized.expand(
        [
            ("fractional_speed", {"session_recording_id": "s1", "playback_speed": 1.5}, "playback_speed", 1.5),
            ("integer_speed", {"session_recording_id": "s1", "playback_speed": 8}, "playback_speed", 8),
            ("fractional_trim", {"session_recording_id": "s1", "trim": 30.5}, "trim", 30.5),
        ]
    )
    def test_fractional_values(self, _name, export_context, field, expected_value):
        asset = _make_asset(pk=50, export_context=export_context)

        mock_qs = MagicMock()
        mock_qs.select_related.return_value.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            result = build_rasterization_input(50)

        assert getattr(result, field) == expected_value


class TestFinalizeRasterization:
    def _make_result(self, **overrides) -> RasterizationActivityOutput:
        defaults = {
            "s3_uri": "s3://posthog/exports/mp4/team-1/task-42/video.mp4",
            "video_duration_s": 10.0,
            "playback_speed": 4.0,
        }
        defaults.update(overrides)
        return RasterizationActivityOutput(**defaults)

    def test_happy_path(self):
        asset = _make_asset(pk=42, export_context={"session_recording_id": "s1"})
        result = self._make_result(
            file_size_bytes=12345,
            truncated=True,
        )

        mock_qs = MagicMock()
        mock_qs.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            finalize_rasterization(FinalizeRasterizationInput(exported_asset_id=42, result=result))

        assert asset.content_location == "exports/mp4/team-1/task-42/video.mp4"
        assert asset.export_context["video_duration_s"] == 10.0
        assert asset.export_context["playback_speed"] == 4.0
        assert asset.export_context["truncated"] is True
        assert asset.export_context["file_size_bytes"] == 12345
        assert asset.export_context["session_recording_id"] == "s1"
        asset.save.assert_called_once_with(update_fields=["content_location", "export_context"])

    def test_wrong_s3_prefix_raises(self):
        asset = _make_asset(pk=42)
        result = self._make_result(s3_uri="s3://wrong-bucket/path/video.mp4")

        mock_qs = MagicMock()
        mock_qs.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            with pytest.raises(ValueError, match="Unexpected s3_uri prefix"):
                finalize_rasterization(FinalizeRasterizationInput(exported_asset_id=42, result=result))

        asset.save.assert_not_called()

    def test_null_export_context_initialized(self):
        asset = _make_asset(pk=42, export_context=None)
        result = self._make_result()

        mock_qs = MagicMock()
        mock_qs.get.return_value = asset

        with (
            patch("posthog.temporal.session_replay.rasterize_recording.activities.ExportedAsset.objects", mock_qs),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.settings", MOCK_SETTINGS),
            patch("posthog.temporal.session_replay.rasterize_recording.activities.close_old_connections"),
        ):
            finalize_rasterization(FinalizeRasterizationInput(exported_asset_id=42, result=result))

        assert asset.export_context is not None
        assert "video_duration_s" in asset.export_context
        asset.save.assert_called_once()
