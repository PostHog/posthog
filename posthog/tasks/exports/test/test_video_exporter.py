import os
import tempfile

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from posthog.tasks.exports import video_exporter


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
                        image_path=tmp_file.name,
                        url_to_render="http://localhost:8000/exporter?token=test",
                        screenshot_width=1400,
                        wait_for_css_selector=".replayer-wrapper",
                        screenshot_height=600,
                        recording_duration=5,
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
        mock_playwright_instance, mock_page = self._setup_playwright_mocks(mock_playwright, mock_which)

        with patch("posthog.tasks.exports.video_exporter.shutil.move") as mock_move:
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_file:
                try:
                    video_exporter.record_replay_to_file(
                        image_path=tmp_file.name,
                        url_to_render="http://localhost:8000/exporter?token=test",
                        screenshot_width=1400,
                        wait_for_css_selector=".replayer-wrapper",
                        screenshot_height=600,
                        recording_duration=5,
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
                        image_path=tmp_file.name,
                        url_to_render="http://localhost:8000/exporter?token=test",
                        screenshot_width=1400,
                        wait_for_css_selector=".replayer-wrapper",
                        screenshot_height=600,
                        recording_duration=5,
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
                            image_path=tmp_file.name,
                            url_to_render="http://localhost:8000/exporter?token=test",
                            screenshot_width=1400,
                            wait_for_css_selector=".replayer-wrapper",
                            screenshot_height=600,
                            recording_duration=5,
                        )
                finally:
                    if os.path.exists(tmp_file.name):
                        os.unlink(tmp_file.name)

    def test_record_replay_to_file_input_validation(self) -> None:
        """Test input parameter validation catches invalid values."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
            try:
                # Test invalid recording duration
                with pytest.raises(ValueError, match="recording_duration must be positive"):
                    video_exporter.record_replay_to_file(
                        image_path=tmp_file.name,
                        url_to_render="http://localhost:8000/exporter?token=test",
                        screenshot_width=1400,
                        wait_for_css_selector=".replayer-wrapper",
                        screenshot_height=600,
                        recording_duration=0,
                    )

                # Test invalid dimensions
                with pytest.raises(ValueError, match="screenshot_width must be positive"):
                    video_exporter.record_replay_to_file(
                        image_path=tmp_file.name,
                        url_to_render="http://localhost:8000/exporter?token=test",
                        screenshot_width=0,  # Intentionally invalid for testing
                        wait_for_css_selector=".replayer-wrapper",
                        screenshot_height=600,
                        recording_duration=5,
                    )

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
                        image_path=tmp_file.name,
                        url_to_render="http://localhost:8000/exporter?token=test",
                        screenshot_width=None,  # Should trigger auto-detection
                        wait_for_css_selector=".replayer-wrapper",
                        screenshot_height=None,  # Should trigger auto-detection
                        recording_duration=5,
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

    @patch("posthog.tasks.exports.video_exporter.sync_playwright")
    @patch("posthog.tasks.exports.video_exporter.shutil.which")
    def test_record_replay_to_file_dimension_scaling(self, mock_which: Mock, mock_playwright: Mock) -> None:
        mock_playwright_instance, mock_recording_page = self._setup_playwright_mocks(mock_playwright, mock_which)

        # Mock browser context creation to capture the viewport dimensions
        mock_browser = mock_playwright_instance.chromium.launch.return_value
        mock_context = Mock()
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_recording_page

        with patch("posthog.tasks.exports.video_exporter.subprocess.run") as mock_subprocess:
            mock_subprocess.return_value = Mock(returncode=0)

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
                try:
                    # Test with large landscape dimensions (1920x1080 should scale to 1400x787)
                    video_exporter.record_replay_to_file(
                        image_path=tmp_file.name,
                        url_to_render="http://localhost:8000/exporter?token=test",
                        screenshot_width=1920,  # Large width
                        wait_for_css_selector=".replayer-wrapper",
                        screenshot_height=1080,  # Proportional height
                        recording_duration=5,
                    )

                    # Verify browser context was created with scaled dimensions
                    mock_browser.new_context.assert_called_once()
                    context_call = mock_browser.new_context.call_args
                    viewport = context_call[1]["viewport"]

                    # Should be scaled down to fit 1400px width while maintaining aspect ratio
                    assert viewport["width"] == 1400
                    assert viewport["height"] == 787  # 1080 * (1400/1920) = 787.5 -> 787

                    # Verify record_video_size matches viewport
                    record_video_size = context_call[1]["record_video_size"]
                    assert record_video_size["width"] == 1400
                    assert record_video_size["height"] == 787

                finally:
                    if os.path.exists(tmp_file.name):
                        os.unlink(tmp_file.name)

    @patch("posthog.tasks.exports.video_exporter.sync_playwright")
    @patch("posthog.tasks.exports.video_exporter.shutil.which")
    def test_record_replay_to_file_portrait_dimension_scaling(self, mock_which: Mock, mock_playwright: Mock) -> None:
        mock_playwright_instance, mock_recording_page = self._setup_playwright_mocks(mock_playwright, mock_which)

        # Mock browser context creation to capture the viewport dimensions
        mock_browser = mock_playwright_instance.chromium.launch.return_value
        mock_context = Mock()
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_recording_page

        with patch("posthog.tasks.exports.video_exporter.subprocess.run") as mock_subprocess:
            mock_subprocess.return_value = Mock(returncode=0)

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
                try:
                    # Test with large portrait dimensions (1080x1920 should scale to 787x1400)
                    video_exporter.record_replay_to_file(
                        image_path=tmp_file.name,
                        url_to_render="http://localhost:8000/exporter?token=test",
                        screenshot_width=1080,  # Width smaller than height
                        wait_for_css_selector=".replayer-wrapper",
                        screenshot_height=1920,  # Large height
                        recording_duration=5,
                    )

                    # Verify browser context was created with scaled dimensions
                    mock_browser.new_context.assert_called_once()
                    context_call = mock_browser.new_context.call_args
                    viewport = context_call[1]["viewport"]

                    # Should be scaled down to fit 1400px height while maintaining aspect ratio
                    assert viewport["width"] == 787  # 1080 * (1400/1920) = 787.5 -> 787
                    assert viewport["height"] == 1400

                    # Verify record_video_size matches viewport
                    record_video_size = context_call[1]["record_video_size"]
                    assert record_video_size["width"] == 787
                    assert record_video_size["height"] == 1400

                finally:
                    if os.path.exists(tmp_file.name):
                        os.unlink(tmp_file.name)
