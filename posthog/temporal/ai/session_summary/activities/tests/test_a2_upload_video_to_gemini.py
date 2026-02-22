"""
Tests for Activity 2: upload_video_to_gemini_activity

This activity uploads the exported video to Gemini Files API for analysis.
"""

from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import MagicMock, patch

from posthog.models import Team
from posthog.models.exported_asset import ExportedAsset
from posthog.models.user import User
from posthog.temporal.ai.session_summary.activities.a2_upload_video_to_gemini import (
    MAX_PROCESSING_WAIT_SECONDS,
    upload_video_to_gemini_activity,
)
from posthog.temporal.ai.session_summary.activities.tests.conftest import create_video_summary_inputs

from ee.hogai.session_summaries.constants import FULL_VIDEO_EXPORT_FORMAT

pytestmark = pytest.mark.django_db


class TestUploadVideoToGeminiActivity:
    @pytest.mark.asyncio
    async def test_upload_video_to_gemini_success(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_exported_asset: ExportedAsset,
        mock_gemini_file_response: MagicMock,
    ):
        """
        Happy path: video upload succeeds and returns file URI with metadata.

        This is the primary success scenario - file uploads immediately to ACTIVE state.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        mock_client = MagicMock()
        mock_client.files.upload.return_value = mock_gemini_file_response
        mock_client.files.get.return_value = mock_gemini_file_response

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a2_upload_video_to_gemini.RawGenAIClient",
                return_value=mock_client,
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a2_upload_video_to_gemini.get_video_duration_s",
                return_value=120,
            ),
        ):
            result = await upload_video_to_gemini_activity(inputs, mock_exported_asset.id)

            assert result["uploaded_video"].file_uri == mock_gemini_file_response.uri
            assert result["uploaded_video"].mime_type == FULL_VIDEO_EXPORT_FORMAT
            assert result["uploaded_video"].duration == 120
            assert result["team_name"] == ateam.name

            mock_client.files.upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_video_polling_until_active(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_exported_asset: ExportedAsset,
        mock_gemini_processing_file_response: MagicMock,
        mock_gemini_file_response: MagicMock,
    ):
        """
        Async polling behavior: upload waits for file to transition from PROCESSING to ACTIVE.

        Gemini files API processes videos asynchronously, so we must poll until ready.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        mock_client = MagicMock()
        mock_client.files.upload.return_value = mock_gemini_processing_file_response
        # Simulate processing then active
        mock_client.files.get.side_effect = [
            mock_gemini_processing_file_response,  # First poll: still processing
            mock_gemini_file_response,  # Second poll: active
        ]

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a2_upload_video_to_gemini.RawGenAIClient",
                return_value=mock_client,
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a2_upload_video_to_gemini.get_video_duration_s",
                return_value=120,
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a2_upload_video_to_gemini.asyncio.sleep"
            ) as mock_sleep,
        ):
            result = await upload_video_to_gemini_activity(inputs, mock_exported_asset.id)

            assert result["uploaded_video"].file_uri == mock_gemini_file_response.uri
            # Should have called sleep while waiting for processing
            assert mock_sleep.call_count >= 1

    @pytest.mark.asyncio
    async def test_upload_video_processing_timeout(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_exported_asset: ExportedAsset,
        mock_gemini_processing_file_response: MagicMock,
    ):
        """
        Timeout handling: raises error when file processing exceeds MAX_PROCESSING_WAIT_SECONDS.

        We can't wait forever for Gemini to process - there's a reasonable timeout.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        mock_client = MagicMock()
        mock_client.files.upload.return_value = mock_gemini_processing_file_response
        mock_client.files.get.return_value = mock_gemini_processing_file_response  # Always processing

        # Counter to track time.time() calls and simulate passage of time
        call_count = 0

        def mock_time_func():
            nonlocal call_count
            call_count += 1
            # First call: start time (0), subsequent calls: past timeout
            if call_count == 1:
                return 0
            return MAX_PROCESSING_WAIT_SECONDS + 1

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a2_upload_video_to_gemini.RawGenAIClient",
                return_value=mock_client,
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a2_upload_video_to_gemini.get_video_duration_s",
                return_value=120,
            ),
            patch("posthog.temporal.ai.session_summary.activities.a2_upload_video_to_gemini.asyncio.sleep"),
            patch(
                "posthog.temporal.ai.session_summary.activities.a2_upload_video_to_gemini.time.time",
                side_effect=mock_time_func,
            ),
        ):
            with pytest.raises(RuntimeError, match="File processing timed out"):
                await upload_video_to_gemini_activity(inputs, mock_exported_asset.id)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("state_name", "uri", "error_match"),
        [
            ("FAILED", None, "File processing failed"),
            ("ACTIVE", None, "Uploaded file has no URI"),
        ],
        ids=["processing_failed", "no_uri"],
    )
    async def test_upload_video_handles_api_failures(
        self,
        state_name: str,
        uri: str | None,
        error_match: str,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_exported_asset: ExportedAsset,
    ):
        """
        API error handling: raises appropriate error for various Gemini API failure states.

        Both FAILED state and missing URI indicate the upload didn't succeed properly.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        failed_file = MagicMock()
        failed_file.name = "files/abc123"
        failed_file.state = MagicMock()
        failed_file.state.name = state_name
        failed_file.uri = uri

        mock_client = MagicMock()
        mock_client.files.upload.return_value = failed_file

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a2_upload_video_to_gemini.RawGenAIClient",
                return_value=mock_client,
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a2_upload_video_to_gemini.get_video_duration_s",
                return_value=120,
            ),
        ):
            with pytest.raises(RuntimeError, match=error_match):
                await upload_video_to_gemini_activity(inputs, mock_exported_asset.id)

    @pytest.mark.asyncio
    async def test_upload_video_no_content_raises_error(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
    ):
        """
        Input validation: missing video content raises ValueError.

        The asset must have actual video bytes to upload.
        """
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        # Create asset with no content
        asset = await ExportedAsset.objects.acreate(
            team_id=ateam.id,
            export_format=FULL_VIDEO_EXPORT_FORMAT,
            export_context={"session_recording_id": mock_video_session_id},
            created_by_id=auser.id,
            created_at=datetime.now(UTC),
            expires_after=datetime.now(UTC) + timedelta(days=7),
            content=None,
            content_location=None,
        )

        try:
            with pytest.raises(ValueError, match="No video content found"):
                await upload_video_to_gemini_activity(inputs, asset.id)
        finally:
            await asset.adelete()
