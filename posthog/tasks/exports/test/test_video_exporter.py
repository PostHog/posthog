import os
import tempfile
from contextlib import nullcontext

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.tasks.exports import video_exporter
from posthog.tasks.exports.video_exporter import RecordReplayToFileOptions


class TestVideoExporter(APIBaseTest):
    def _setup_playwright_mocks(self, mock_playwright: Mock, mock_which: Mock) -> tuple[Mock, Mock]:
        """Helper to setup common Playwright mocks."""
        mock_which.return_value = "/usr/bin/ffmpeg"

        mock_browser = Mock()
        mock_context = Mock()
        mock_page = Mock()
        mock_video = Mock()

        mock_playwright_instance = Mock()
        mock_playwright.return_value.__enter__.return_value = mock_playwright_instance
        mock_playwright_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_page.video = mock_video

        # Mock page interactions
        mock_page.goto.return_value = None
        mock_page.wait_for_selector.return_value = None
        mock_page.wait_for_timeout.return_value = None
        mock_page.evaluate.return_value = {"height": 800, "width": 1400}
        mock_page.set_viewport_size.return_value = None
        mock_page.close.return_value = None
        mock_video.save_as.return_value = None

        return mock_playwright_instance, mock_page

    @patch("posthog.tasks.exports.video_exporter.sync_playwright")
    @patch("posthog.tasks.exports.video_exporter.shutil.which")
    def test_record_replay_to_file_mp4_success(self, mock_which: Mock, mock_playwright: Mock) -> None:
        """Test successful MP4 video recording with ffmpeg conversion."""
        mock_playwright_instance, mock_page = self._setup_playwright_mocks(mock_playwright, mock_which)

        with patch("posthog.tasks.exports.video_exporter.subprocess.run") as mock_subprocess:
            mock_subprocess.return_value = Mock(returncode=0)

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
                try:
                    video_exporter.record_replay_to_file(
                        RecordReplayToFileOptions(
                            image_path=tmp_file.name,
                            url_to_render="http://localhost:8000/exporter?token=test",
                            wait_for_css_selector=".replayer-wrapper",
                            recording_duration=5,
                            screenshot_width=1400,
                            screenshot_height=600,
                        )
                    )

                    # Verify core functionality
                    mock_playwright_instance.chromium.launch.assert_called_once()
                    mock_page.goto.assert_called_once()
                    mock_subprocess.assert_called_once()

                    # Verify ffmpeg was called for MP4 conversion
                    ffmpeg_args = mock_subprocess.call_args[0][0]
                    assert "ffmpeg" in ffmpeg_args
                    assert "libx264" in ffmpeg_args

                finally:
                    if os.path.exists(tmp_file.name):
                        os.unlink(tmp_file.name)

    @patch("posthog.tasks.exports.video_exporter.sync_playwright")
    @patch("posthog.tasks.exports.video_exporter.shutil.which")
    def test_record_replay_to_file_webm_success(self, mock_which: Mock, mock_playwright: Mock) -> None:
        """Test successful WebM recording (no ffmpeg conversion needed)."""
        self._setup_playwright_mocks(mock_playwright, mock_which)

        with patch("posthog.tasks.exports.video_exporter.shutil.move") as mock_move:
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_file:
                try:
                    video_exporter.record_replay_to_file(
                        RecordReplayToFileOptions(
                            image_path=tmp_file.name,
                            url_to_render="http://localhost:8000/exporter?token=test",
                            wait_for_css_selector=".replayer-wrapper",
                            recording_duration=5,
                            screenshot_width=1400,
                            screenshot_height=600,
                        )
                    )

                    # Verify WebM uses direct file move (no ffmpeg conversion)
                    mock_move.assert_called_once()

                finally:
                    if os.path.exists(tmp_file.name):
                        os.unlink(tmp_file.name)

    @patch("posthog.tasks.exports.video_exporter.shutil.which")
    def test_record_replay_to_file_missing_ffmpeg(self, mock_which: Mock) -> None:
        """Test error when ffmpeg is not available for MP4/GIF exports."""
        mock_which.return_value = None  # ffmpeg not found

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
            try:
                with pytest.raises(RuntimeError, match="ffmpeg is required"):
                    video_exporter.record_replay_to_file(
                        RecordReplayToFileOptions(
                            image_path=tmp_file.name,
                            url_to_render="http://localhost:8000/exporter?token=test",
                            wait_for_css_selector=".replayer-wrapper",
                            recording_duration=5,
                            screenshot_width=1400,
                            screenshot_height=600,
                        )
                    )
            finally:
                if os.path.exists(tmp_file.name):
                    os.unlink(tmp_file.name)

    @patch("posthog.tasks.exports.video_exporter.sync_playwright")
    @patch("posthog.tasks.exports.video_exporter.shutil.which")
    def test_record_replay_to_file_ffmpeg_failure(self, mock_which: Mock, mock_playwright: Mock) -> None:
        """Test error handling when ffmpeg conversion fails."""
        mock_playwright_instance, mock_page = self._setup_playwright_mocks(mock_playwright, mock_which)

        with patch("posthog.tasks.exports.video_exporter.subprocess.run") as mock_subprocess:
            from subprocess import CalledProcessError

            mock_subprocess.side_effect = CalledProcessError(
                returncode=1, cmd=["ffmpeg"], stderr="ffmpeg conversion error"
            )

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
                try:
                    with pytest.raises(RuntimeError, match="ffmpeg failed with exit code 1"):
                        video_exporter.record_replay_to_file(
                            RecordReplayToFileOptions(
                                image_path=tmp_file.name,
                                url_to_render="http://localhost:8000/exporter?token=test",
                                wait_for_css_selector=".replayer-wrapper",
                                recording_duration=5,
                                screenshot_width=1400,
                                screenshot_height=600,
                            )
                        )
                finally:
                    if os.path.exists(tmp_file.name):
                        os.unlink(tmp_file.name)

    @parameterized.expand(
        [
            ("zero_recording_duration", {"recording_duration": 0}, ValueError, "recording_duration must be positive"),
            ("zero_width", {"screenshot_width": 0}, ValueError, "screenshot_width must be positive"),
            (
                "playback_speed_too_low",
                {"playback_speed": 0},
                ValueError,
                "playback_speed must be between 1 and 360",
            ),
            (
                "playback_speed_too_high",
                {"playback_speed": 361},
                ValueError,
                "playback_speed must be between 1 and 360",
            ),
            ("valid_playback_speed_min", {"playback_speed": 1}, None, None),
            ("valid_playback_speed_max", {"playback_speed": 360}, None, None),
        ]
    )
    def test_validation(
        self, _name: str, overrides: dict, expected_error: type[Exception] | None, error_match: str | None
    ) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
            try:
                base_opts = {
                    "image_path": tmp_file.name,
                    "url_to_render": "http://localhost:8000/exporter?token=test",
                    "wait_for_css_selector": ".replayer-wrapper",
                    "recording_duration": 5,
                    "screenshot_width": 1400,
                    "screenshot_height": 600,
                }
                opts_dict = {**base_opts, **overrides}

                error_context_manager = (
                    pytest.raises(expected_error, match=error_match) if expected_error else nullcontext()
                )
                with error_context_manager:
                    RecordReplayToFileOptions(**opts_dict)

            finally:
                if os.path.exists(tmp_file.name):
                    os.unlink(tmp_file.name)

    @patch("posthog.tasks.exports.video_exporter.sync_playwright")
    @patch("posthog.tasks.exports.video_exporter.shutil.which")
    def test_record_replay_to_file_auto_detect_dimensions(self, mock_which: Mock, mock_playwright: Mock) -> None:
        mock_playwright_instance, mock_recording_page = self._setup_playwright_mocks(mock_playwright, mock_which)

        # Additional mocks for the detection phase
        mock_browser = mock_playwright_instance.chromium.launch.return_value
        mock_detection_context = Mock()
        mock_detection_page = Mock()
        mock_recording_context = Mock()

        # First call to new_context is for detection, second is for recording
        mock_browser.new_context.side_effect = [mock_detection_context, mock_recording_context]
        mock_detection_context.new_page.return_value = mock_detection_page
        mock_recording_context.new_page.return_value = mock_recording_page

        # Mock the resolution detection global variable wait
        mock_resolution_result = Mock()
        mock_resolution_result.json_value.return_value = {"width": 1920, "height": 1080}
        mock_detection_page.wait_for_function.return_value = mock_resolution_result

        with patch("posthog.tasks.exports.video_exporter.subprocess.run") as mock_subprocess:
            mock_subprocess.return_value = Mock(returncode=0)

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
                try:
                    video_exporter.record_replay_to_file(
                        RecordReplayToFileOptions(
                            image_path=tmp_file.name,
                            url_to_render="http://localhost:8000/exporter?token=test",
                            wait_for_css_selector=".replayer-wrapper",
                            recording_duration=5,
                            screenshot_width=None,
                            screenshot_height=None,
                        )
                    )

                    # Verify detection flow was called
                    mock_detection_page.goto.assert_called_once()
                    mock_detection_page.wait_for_function.assert_called_once()
                    mock_detection_page.close.assert_called_once()
                    mock_detection_context.close.assert_called_once()

                    # Verify recording context was created with scaled dimensions (1920x1080 -> 1400x787)
                    assert mock_browser.new_context.call_count == 2  # Detection + recording contexts
                    recording_context_call = mock_browser.new_context.call_args_list[1]
                    viewport = recording_context_call[1]["viewport"]
                    assert viewport["width"] == 1400  # Scaled down from 1920
                    assert viewport["height"] == 787  # Scaled down from 1080 (1080 * 1400/1920 = 787.5 -> 787)

                finally:
                    if os.path.exists(tmp_file.name):
                        os.unlink(tmp_file.name)

    @parameterized.expand(
        [
            ("landscape", 1920, 1080, 1400, 787),
            ("portrait", 1080, 1920, 787, 1400),
        ]
    )
    @patch("posthog.tasks.exports.video_exporter.sync_playwright")
    @patch("posthog.tasks.exports.video_exporter.shutil.which")
    def test_dimension_scaling(
        self,
        _name: str,
        input_width: int,
        input_height: int,
        expected_width: int,
        expected_height: int,
        mock_which: Mock,
        mock_playwright: Mock,
    ) -> None:
        mock_playwright_instance, mock_recording_page = self._setup_playwright_mocks(mock_playwright, mock_which)

        mock_browser = mock_playwright_instance.chromium.launch.return_value
        mock_context = Mock()
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_recording_page

        with patch("posthog.tasks.exports.video_exporter.subprocess.run") as mock_subprocess:
            mock_subprocess.return_value = Mock(returncode=0)

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
                try:
                    video_exporter.record_replay_to_file(
                        RecordReplayToFileOptions(
                            image_path=tmp_file.name,
                            url_to_render="http://localhost:8000/exporter?token=test",
                            wait_for_css_selector=".replayer-wrapper",
                            recording_duration=5,
                            screenshot_width=input_width,
                            screenshot_height=input_height,
                        )
                    )

                    mock_browser.new_context.assert_called_once()
                    context_call = mock_browser.new_context.call_args
                    viewport = context_call[1]["viewport"]
                    record_video_size = context_call[1]["record_video_size"]

                    assert viewport["width"] == expected_width
                    assert viewport["height"] == expected_height
                    assert record_video_size["width"] == expected_width
                    assert record_video_size["height"] == expected_height

                finally:
                    if os.path.exists(tmp_file.name):
                        os.unlink(tmp_file.name)

    @parameterized.expand(
        [
            ("user_speed_respected", ".mp4", 8, 10, "setpts=8*PTS", False),
            ("automatic_speed_for_long_mp4", ".mp4", 1, 10, "setpts=4*PTS", False),
            ("automatic_speed_for_long_webm", ".webm", 1, 10, "setpts=4*PTS", False),
            ("user_speed_overrides_automatic_speedup", ".mp4", 30, 10, "setpts=30*PTS", False),
            ("short_video_no_automatic_speedup", ".mp4", 1, 5, None, False),
            ("short_webm_no_processing", ".webm", 1, 5, None, True),
        ]
    )
    @patch("posthog.tasks.exports.video_exporter.sync_playwright")
    @patch("posthog.tasks.exports.video_exporter.shutil.which")
    def test_playback_speed_behavior(
        self,
        _name: str,
        file_ext: str,
        playback_speed: int,
        duration: int,
        expected_ffmpeg_arg: str | None,
        uses_move: bool,
        mock_which: Mock,
        mock_playwright: Mock,
    ) -> None:
        self._setup_playwright_mocks(mock_playwright, mock_which)

        with patch("posthog.tasks.exports.video_exporter.subprocess.run") as mock_subprocess:
            mock_subprocess.return_value = Mock(returncode=0)

            with patch("posthog.tasks.exports.video_exporter.shutil.move") as mock_move:
                with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp_file:
                    try:
                        video_exporter.record_replay_to_file(
                            RecordReplayToFileOptions(
                                image_path=tmp_file.name,
                                url_to_render=f"http://localhost:8000/exporter?token=test&playerSpeed={playback_speed}",
                                wait_for_css_selector=".replayer-wrapper",
                                recording_duration=duration,
                                screenshot_width=1400,
                                screenshot_height=600,
                                playback_speed=playback_speed,
                            )
                        )

                        if uses_move:
                            mock_move.assert_called_once()
                            mock_subprocess.assert_not_called()
                        else:
                            ffmpeg_args = mock_subprocess.call_args[0][0]
                            args_str = " ".join(str(arg) for arg in ffmpeg_args)

                            if expected_ffmpeg_arg:
                                assert expected_ffmpeg_arg in args_str
                            else:
                                assert "setpts=" not in " ".join(str(arg) for arg in ffmpeg_args)

                            if file_ext == ".webm":
                                assert "libvpx-vp9" in args_str

                    finally:
                        if os.path.exists(tmp_file.name):
                            os.unlink(tmp_file.name)
