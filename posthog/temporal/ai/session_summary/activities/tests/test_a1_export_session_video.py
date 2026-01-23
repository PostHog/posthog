"""
Tests for Activity 1: export_session_video_activity

This activity exports a session recording as a video file and returns the ExportedAsset ID.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.models import Team
from posthog.models.exported_asset import ExportedAsset
from posthog.models.user import User
from posthog.temporal.ai.session_summary.activities.a1_export_session_video import (
    VIDEO_ANALYSIS_PLAYBACK_SPEED,
    export_session_video_activity,
)
from posthog.temporal.ai.session_summary.activities.tests.conftest import create_video_summary_inputs

from ee.hogai.session_summaries.constants import (
    DEFAULT_VIDEO_EXPORT_MIME_TYPE,
    MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S,
)

pytestmark = pytest.mark.django_db


class TestExportSessionVideoActivity:
    @pytest.mark.asyncio
    async def test_export_session_video_creates_asset_and_triggers_workflow(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_session_metadata: dict[str, Any],
    ):
        """Test successful video export creates ExportedAsset and triggers VideoExportWorkflow."""
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        mock_workflow_handle = MagicMock()
        mock_temporal_client = MagicMock()
        mock_temporal_client.execute_workflow = AsyncMock(return_value=mock_workflow_handle)

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a1_export_session_video.get_team",
                return_value=ateam,
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a1_export_session_video.SessionReplayEvents"
            ) as mock_replay_events,
            patch(
                "posthog.temporal.ai.session_summary.activities.a1_export_session_video.async_connect",
                return_value=mock_temporal_client,
            ),
        ):
            mock_replay_events.return_value.get_metadata.return_value = mock_video_session_metadata

            result = await export_session_video_activity(inputs)

            # Verify an ExportedAsset was created
            assert result is not None
            asset = await ExportedAsset.objects.aget(id=result)
            assert asset.team_id == ateam.id
            assert asset.export_format == DEFAULT_VIDEO_EXPORT_MIME_TYPE
            assert asset.export_context is not None
            assert asset.export_context["session_recording_id"] == mock_video_session_id
            assert asset.export_context["playback_speed"] == VIDEO_ANALYSIS_PLAYBACK_SPEED

            # Verify workflow was triggered
            mock_temporal_client.execute_workflow.assert_called_once()

            # Cleanup
            await asset.adelete()

    @pytest.mark.asyncio
    async def test_export_session_video_reuses_existing_asset(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_exported_asset: ExportedAsset,
    ):
        """Test that existing ExportedAsset is reused instead of creating new one."""
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        with patch(
            "posthog.temporal.ai.session_summary.activities.a1_export_session_video.async_connect"
        ) as mock_connect:
            result = await export_session_video_activity(inputs)

            # Should return existing asset ID
            assert result == mock_exported_asset.id

            # Should not trigger new workflow
            mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_session_video_session_too_short_from_metadata(
        self,
        ateam: Team,
        auser: User,
        mock_short_session_metadata: dict[str, Any],
    ):
        """Test that sessions shorter than MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S return None."""
        short_session_id = "00000000-0000-0000-0002-000000000001"
        inputs = create_video_summary_inputs(short_session_id, ateam.id, auser.id)

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a1_export_session_video.get_team",
                return_value=ateam,
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a1_export_session_video.SessionReplayEvents"
            ) as mock_replay_events,
        ):
            mock_replay_events.return_value.get_metadata.return_value = mock_short_session_metadata

            result = await export_session_video_activity(inputs)

            # Should return None for too-short sessions
            assert result is None

    @pytest.mark.asyncio
    async def test_export_session_video_session_too_short_from_existing_asset(
        self,
        ateam: Team,
        auser: User,
    ):
        """Test that existing asset with short duration returns None."""
        short_session_id = "00000000-0000-0000-0002-000000000002"
        inputs = create_video_summary_inputs(short_session_id, ateam.id, auser.id)

        # Create asset with short duration
        short_asset = await ExportedAsset.objects.acreate(
            team_id=ateam.id,
            export_format=DEFAULT_VIDEO_EXPORT_MIME_TYPE,
            export_context={
                "session_recording_id": short_session_id,
                "duration": MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S - 1,  # Too short
            },
            created_by_id=auser.id,
            created_at=datetime.now(UTC),
            expires_after=datetime.now(UTC) + timedelta(days=7),
            content=b"fake",
        )

        try:
            result = await export_session_video_activity(inputs)
            assert result is None
        finally:
            await short_asset.adelete()

    @pytest.mark.asyncio
    async def test_export_session_video_no_metadata_raises_error(
        self,
        ateam: Team,
        auser: User,
    ):
        """Test that missing session metadata raises ValueError."""
        session_id = "00000000-0000-0000-0002-000000000003"
        inputs = create_video_summary_inputs(session_id, ateam.id, auser.id)

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a1_export_session_video.get_team",
                return_value=ateam,
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a1_export_session_video.SessionReplayEvents"
            ) as mock_replay_events,
        ):
            mock_replay_events.return_value.get_metadata.return_value = None

            with pytest.raises(ValueError, match="No metadata found"):
                await export_session_video_activity(inputs)

    @pytest.mark.asyncio
    async def test_export_session_video_sets_correct_export_context(
        self,
        ateam: Team,
        auser: User,
        mock_video_session_id: str,
        mock_video_session_metadata: dict[str, Any],
    ):
        """Test that export context includes all required fields."""
        inputs = create_video_summary_inputs(mock_video_session_id, ateam.id, auser.id)

        mock_temporal_client = MagicMock()
        mock_temporal_client.execute_workflow = AsyncMock()

        with (
            patch(
                "posthog.temporal.ai.session_summary.activities.a1_export_session_video.get_team",
                return_value=ateam,
            ),
            patch(
                "posthog.temporal.ai.session_summary.activities.a1_export_session_video.SessionReplayEvents"
            ) as mock_replay_events,
            patch(
                "posthog.temporal.ai.session_summary.activities.a1_export_session_video.async_connect",
                return_value=mock_temporal_client,
            ),
        ):
            mock_replay_events.return_value.get_metadata.return_value = mock_video_session_metadata

            result = await export_session_video_activity(inputs)

            asset = await ExportedAsset.objects.aget(id=result)

            # Verify all expected context fields
            assert asset.export_context is not None
            assert asset.export_context["session_recording_id"] == mock_video_session_id
            assert asset.export_context["timestamp"] == 0
            assert "filename" in asset.export_context
            assert asset.export_context["duration"] == mock_video_session_metadata["duration"]
            assert asset.export_context["playback_speed"] == VIDEO_ANALYSIS_PLAYBACK_SPEED
            assert asset.export_context["mode"] == "video"

            # Cleanup
            await asset.adelete()
