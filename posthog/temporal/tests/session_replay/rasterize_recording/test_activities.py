import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.session_replay.rasterize_recording.activities import (
    build_rasterization_input,
    finalize_rasterization,
)
from posthog.temporal.session_replay.rasterize_recording.types import (
    FinalizeRasterizationInput,
    InactivityPeriod,
    RasterizationActivityInput,
    RasterizationActivityOutput,
    compute_params_fingerprint,
)

MOCK_SETTINGS = MagicMock()
MOCK_SETTINGS.OBJECT_STORAGE_BUCKET = "posthog"
MOCK_SETTINGS.OBJECT_STORAGE_EXPORTS_FOLDER = "exports"


def _make_asset(
    pk: int = 42,
    team_id: int = 1,
    export_context: dict | None = None,
    export_format: str = "video/mp4",
    content_location: str | None = None,
) -> MagicMock:
    asset = MagicMock()
    asset.pk = pk
    asset.id = pk
    asset.team_id = team_id
    asset.export_context = export_context
    asset.export_format = export_format
    asset.content_location = content_location
    asset.save = MagicMock()
    return asset


def _patches(asset: MagicMock, head_object_return: dict | None = None):
    mock_qs = MagicMock()
    mock_qs.select_related.return_value.get.return_value = asset
    mock_qs.get.return_value = asset
    # finalize_rasterization wraps its read-modify-write in transaction.atomic
    # + select_for_update; both need to be mockable here.
    mock_qs.select_for_update.return_value.get.return_value = asset
    head_mock = MagicMock(return_value=head_object_return)

    class _NoopAtomic:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    return (
        patch(
            "posthog.temporal.session_replay.rasterize_recording.activities.rasterize.ExportedAsset.objects", mock_qs
        ),
        patch("posthog.temporal.session_replay.rasterize_recording.activities.rasterize.settings", MOCK_SETTINGS),
        patch("posthog.temporal.session_replay.rasterize_recording.activities.rasterize.close_old_connections"),
        patch(
            "posthog.temporal.session_replay.rasterize_recording.activities.rasterize.object_storage.head_object",
            head_mock,
        ),
        patch(
            "posthog.temporal.session_replay.rasterize_recording.activities.rasterize.transaction.atomic",
            return_value=_NoopAtomic(),
        ),
    ), head_mock


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

        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(42)

        assert result.cached_output is None
        assert result.activity_input is not None
        assert result.render_fingerprint  # non-empty
        ai = result.activity_input
        assert ai.session_id == "abc123"
        assert ai.team_id == 7
        assert ai.s3_bucket == "posthog"
        assert ai.s3_key_prefix == "exports/mp4/team-7/task-42"
        assert ai.playback_speed == 8
        assert ai.recording_fps == 30
        assert ai.trim == 60.5
        assert ai.show_metadata_footer is True
        assert ai.viewport_width == 1920
        assert ai.viewport_height == 1080
        assert ai.start_offset_s == 10.0
        assert ai.end_offset_s == 70.0
        assert ai.output_format == "mp4"
        assert ai.skip_inactivity is False
        assert ai.mouse_tail is False
        assert ai.max_virtual_time == 300.0

    def test_defaults(self):
        asset = _make_asset(pk=10, team_id=3, export_context={"session_recording_id": "sess-1"})
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(10)

        ai = result.activity_input
        assert ai is not None
        assert ai.session_id == "sess-1"
        assert ai.playback_speed == 4
        assert ai.recording_fps == 24
        assert ai.trim is None
        assert ai.max_virtual_time is None
        assert ai.show_metadata_footer is False
        assert ai.viewport_width is None
        assert ai.viewport_height is None
        assert ai.start_offset_s is None
        assert ai.end_offset_s is None
        assert ai.output_format == "mp4"
        assert ai.skip_inactivity is True
        assert ai.mouse_tail is True

    def test_missing_session_id_raises(self):
        asset = _make_asset(pk=99, export_context={"playback_speed": 4})
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with pytest.raises(ValueError, match="no session_recording_id"):
                build_rasterization_input(99)

    def test_none_export_context_raises(self):
        asset = _make_asset(pk=100, export_context=None)
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with pytest.raises(ValueError, match="no session_recording_id"):
                build_rasterization_input(100)

    def test_timestamp_and_duration_mapped_to_offsets(self):
        asset = _make_asset(
            pk=50,
            export_context={"session_recording_id": "s1", "timestamp": 10, "duration": 30},
        )
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)

        ai = result.activity_input
        assert ai is not None
        assert ai.start_offset_s == 10
        assert ai.end_offset_s == 40

    def test_duration_without_timestamp(self):
        asset = _make_asset(pk=50, export_context={"session_recording_id": "s1", "duration": 30})
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)

        ai = result.activity_input
        assert ai is not None
        assert ai.start_offset_s is None
        assert ai.end_offset_s == 30

    def test_webm_export_format(self):
        asset = _make_asset(pk=50, export_format="video/webm", export_context={"session_recording_id": "s1"})
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)
        ai = result.activity_input
        assert ai is not None
        assert ai.output_format == "webm"
        assert ai.s3_key_prefix == "exports/webm/team-1/task-50"

    def test_gif_export_format(self):
        asset = _make_asset(pk=50, export_format="image/gif", export_context={"session_recording_id": "s1"})
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)
        ai = result.activity_input
        assert ai is not None
        assert ai.output_format == "gif"
        assert ai.s3_key_prefix == "exports/gif/team-1/task-50"

    def test_start_offset_zero_not_treated_as_falsy(self):
        asset = _make_asset(
            pk=50,
            export_context={"session_recording_id": "s1", "start_offset_s": 0, "timestamp": 999},
        )
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)
        assert result.activity_input is not None
        assert result.activity_input.start_offset_s == 0

    def test_viewport_dimensions_clamped(self):
        asset = _make_asset(
            pk=50,
            export_context={"session_recording_id": "s1", "width": 200, "height": 5000},
        )
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)
        ai = result.activity_input
        assert ai is not None
        assert ai.viewport_width == 400
        assert ai.viewport_height == 2160

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
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)
        assert result.activity_input is not None
        assert result.activity_input.playback_speed == expected_speed

    @parameterized.expand(
        [
            ("fractional_speed", {"session_recording_id": "s1", "playback_speed": 1.5}, "playback_speed", 1.5),
            ("integer_speed", {"session_recording_id": "s1", "playback_speed": 8}, "playback_speed", 8),
            ("fractional_trim", {"session_recording_id": "s1", "trim": 30.5}, "trim", 30.5),
        ]
    )
    def test_fractional_values(self, _name, export_context, field, expected_value):
        asset = _make_asset(pk=50, export_context=export_context)
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)
        assert result.activity_input is not None
        assert getattr(result.activity_input, field) == expected_value


class TestBuildRasterizationCache:
    def _ctx_with_render(self, fingerprint: str, **overrides) -> dict:
        ctx = {
            "session_recording_id": "s1",
            "playback_speed": 4,
            "recording_fps": 24,
            "show_metadata_footer": False,
            "video_duration_s": 12.5,
            "truncated": False,
            "file_size_bytes": 99000,
            "inactivity_periods": [],
            "render_fingerprint": fingerprint,
        }
        ctx.update(overrides)
        return ctx

    def _fingerprint_for(self, asset: MagicMock) -> str:
        patches, _ = _patches(asset, head_object_return=None)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(asset.pk)
        assert result.activity_input is not None
        return compute_params_fingerprint(result.activity_input)

    def test_cache_hit_returns_synthesized_output(self):
        # First call computes the fingerprint we'll persist.
        asset = _make_asset(pk=50, export_context={"session_recording_id": "s1"})
        fp = self._fingerprint_for(asset)

        # Second call: asset has matching fingerprint + content_location + S3 HEAD = 200.
        cached_asset = _make_asset(
            pk=50,
            export_context=self._ctx_with_render(fp),
            content_location="exports/mp4/team-1/task-50/video.mp4",
        )
        patches, head_mock = _patches(cached_asset, head_object_return={"ContentLength": 99000})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)

        head_mock.assert_called_once_with(file_key="exports/mp4/team-1/task-50/video.mp4")
        assert result.activity_input is None
        assert result.cached_output is not None
        assert result.cached_output.s3_uri == "s3://posthog/exports/mp4/team-1/task-50/video.mp4"
        assert result.cached_output.video_duration_s == 12.5
        assert result.cached_output.file_size_bytes == 99000
        assert result.cached_output.truncated is False
        assert result.cached_output.inactivity_periods == []

    def test_cache_miss_when_fingerprint_differs(self):
        asset = _make_asset(
            pk=50,
            export_context=self._ctx_with_render("0" * 16),  # fake fingerprint
            content_location="exports/mp4/team-1/task-50/video.mp4",
        )
        patches, head_mock = _patches(asset, head_object_return={"ContentLength": 99000})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)

        # No HEAD call because fingerprint check fails first.
        head_mock.assert_not_called()
        assert result.cached_output is None
        assert result.activity_input is not None

    def test_cache_miss_when_no_content_location(self):
        asset = _make_asset(
            pk=50,
            export_context=self._ctx_with_render("0" * 16),
            content_location=None,
        )
        patches, head_mock = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)

        head_mock.assert_not_called()
        assert result.cached_output is None
        assert result.activity_input is not None

    def test_cache_miss_when_s3_object_missing(self):
        asset = _make_asset(pk=50, export_context={"session_recording_id": "s1"})
        fp = self._fingerprint_for(asset)

        gone_asset = _make_asset(
            pk=50,
            export_context=self._ctx_with_render(fp),
            content_location="exports/mp4/team-1/task-50/video.mp4",
        )
        patches, head_mock = _patches(gone_asset, head_object_return=None)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)

        head_mock.assert_called_once()
        assert result.cached_output is None
        assert result.activity_input is not None

    def test_cache_miss_when_persisted_output_fields_missing(self):
        asset = _make_asset(pk=50, export_context={"session_recording_id": "s1"})
        fp = self._fingerprint_for(asset)

        # Drop file_size_bytes — schema-drift case.
        ctx = self._ctx_with_render(fp)
        del ctx["file_size_bytes"]
        partial_asset = _make_asset(
            pk=50,
            export_context=ctx,
            content_location="exports/mp4/team-1/task-50/video.mp4",
        )
        patches, _ = _patches(partial_asset, head_object_return={"ContentLength": 99000})
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = build_rasterization_input(50)

        assert result.cached_output is None
        assert result.activity_input is not None


class TestFingerprint:
    def _make_input(self, **overrides) -> RasterizationActivityInput:
        defaults = {
            "team_id": 1,
            "session_id": "s1",
            "s3_bucket": "posthog",
            "s3_key_prefix": "exports/mp4/team-1/task-1",
            "playback_speed": 4,
            "recording_fps": 24,
            "show_metadata_footer": False,
            "output_format": "mp4",
            "skip_inactivity": True,
            "mouse_tail": True,
        }
        defaults.update(overrides)
        return RasterizationActivityInput(**defaults)

    def test_stable_for_identical_inputs(self):
        a = self._make_input()
        b = self._make_input()
        assert compute_params_fingerprint(a) == compute_params_fingerprint(b)

    def test_excludes_destination_fields(self):
        a = self._make_input(s3_bucket="bucket-a", s3_key_prefix="prefix-a")
        b = self._make_input(s3_bucket="bucket-b", s3_key_prefix="prefix-b")
        assert compute_params_fingerprint(a) == compute_params_fingerprint(b)

    def test_excludes_team_and_session(self):
        a = self._make_input(team_id=1, session_id="s1")
        b = self._make_input(team_id=2, session_id="s2")
        assert compute_params_fingerprint(a) == compute_params_fingerprint(b)

    @parameterized.expand(
        [
            ("playback_speed", {"playback_speed": 8}),
            ("recording_fps", {"recording_fps": 30}),
            ("trim", {"trim": 60.0}),
            ("show_metadata_footer", {"show_metadata_footer": True}),
            ("viewport_width", {"viewport_width": 1920}),
            ("viewport_height", {"viewport_height": 1080}),
            ("start_offset_s", {"start_offset_s": 5.0}),
            ("end_offset_s", {"end_offset_s": 30.0}),
            ("output_format", {"output_format": "webm"}),
            ("skip_inactivity", {"skip_inactivity": False}),
            ("mouse_tail", {"mouse_tail": False}),
            ("max_virtual_time", {"max_virtual_time": 600.0}),
        ]
    )
    def test_diverges_when_render_param_changes(self, _name, override):
        a = self._make_input()
        b = self._make_input(**override)
        assert compute_params_fingerprint(a) != compute_params_fingerprint(b)


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
        result = self._make_result(file_size_bytes=12345, truncated=True)

        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            finalize_rasterization(
                FinalizeRasterizationInput(exported_asset_id=42, result=result, render_fingerprint="abc1234567890def")
            )

        assert asset.content_location == "exports/mp4/team-1/task-42/video.mp4"
        assert asset.export_context["video_duration_s"] == 10.0
        assert asset.export_context["playback_speed"] == 4.0
        assert asset.export_context["truncated"] is True
        assert asset.export_context["file_size_bytes"] == 12345
        assert asset.export_context["session_recording_id"] == "s1"
        assert asset.export_context["render_fingerprint"] == "abc1234567890def"
        asset.save.assert_called_once_with(update_fields=["content_location", "export_context"])

    def test_wrong_s3_prefix_raises(self):
        asset = _make_asset(pk=42)
        result = self._make_result(s3_uri="s3://wrong-bucket/path/video.mp4")
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with pytest.raises(ValueError, match="Unexpected s3_uri prefix"):
                finalize_rasterization(
                    FinalizeRasterizationInput(exported_asset_id=42, result=result, render_fingerprint="x")
                )
        asset.save.assert_not_called()

    def test_null_export_context_initialized(self):
        asset = _make_asset(pk=42, export_context=None)
        result = self._make_result()
        patches, _ = _patches(asset)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            finalize_rasterization(
                FinalizeRasterizationInput(exported_asset_id=42, result=result, render_fingerprint="x")
            )
        assert asset.export_context is not None
        assert "video_duration_s" in asset.export_context
        assert asset.export_context["render_fingerprint"] == "x"
        asset.save.assert_called_once()

    def test_inactivity_periods_round_trip(self):
        period = InactivityPeriod(ts_from_s=1.0, ts_to_s=2.0, active=True)
        as_dict = period.model_dump()
        rebuilt = InactivityPeriod.model_validate(as_dict)
        assert rebuilt == period
