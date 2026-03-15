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

from ee.hogai.session_summaries.constants import FULL_VIDEO_EXPORT_FORMAT, MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S

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
        """
        Happy path: verifies asset creation, workflow trigger, and correct export context.

        This single test covers the full success path because all these assertions verify
        the same data flow - a successful export must create an asset with the right context.
        """
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

            # Verify an ExportedAsset was created with all expected context fields
            assert result is not None
            asset = await ExportedAsset.objects.aget(id=result)
            assert asset.team_id == ateam.id
            assert asset.export_format == FULL_VIDEO_EXPORT_FORMAT
            assert asset.export_context is not None
            assert asset.export_context["session_recording_id"] == mock_video_session_id
            assert asset.export_context["timestamp"] == 0
            assert "filename" in asset.export_context
            assert asset.export_context["duration"] == mock_video_session_metadata["duration"]
            assert asset.export_context["playback_speed"] == VIDEO_ANALYSIS_PLAYBACK_SPEED
            assert asset.export_context["mode"] == "video"

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
        """
        Idempotency guarantee: existing ExportedAsset is reused instead of creating new one.

        This matters because video exports are expensive - we must not re-export if one exists.
        """
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
    @pytest.mark.parametrize(
        ("source", "create_short_asset"),
        [
            ("metadata", False),
            ("existing_asset", True),
        ],
        ids=["from_metadata", "from_existing_asset"],
    )
    async def test_export_session_video_rejects_short_sessions(
        self,
        source: str,
        create_short_asset: bool,
        ateam: Team,
        auser: User,
        mock_short_session_metadata: dict[str, Any],
    ):
        """
        Guard clause: sessions shorter than MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S return None.

        Short sessions don't have enough content for meaningful video analysis, so we reject
        them early. This can happen either from fresh metadata or from an existing short asset.
        """
        short_session_id = f"00000000-0000-0000-0002-00000000000{1 if source == 'metadata' else 2}"
        inputs = create_video_summary_inputs(short_session_id, ateam.id, auser.id)
        short_asset = None

        try:
            if create_short_asset:
                # Create asset with short duration
                short_asset = await ExportedAsset.objects.acreate(
                    team_id=ateam.id,
                    export_format=FULL_VIDEO_EXPORT_FORMAT,
                    export_context={
                        "session_recording_id": short_session_id,
                        "duration": MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S - 1,
                    },
                    created_by_id=auser.id,
                    created_at=datetime.now(UTC),
                    expires_after=datetime.now(UTC) + timedelta(days=7),
                    content=b"fake",
                )
                result = await export_session_video_activity(inputs)
            else:
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

            assert result is None
        finally:
            if short_asset:
                await short_asset.adelete()

    @pytest.mark.asyncio
    async def test_export_session_video_no_metadata_raises_error(
        self,
        ateam: Team,
        auser: User,
    ):
        """
        Error guard: missing session metadata raises ValueError.

        If ClickHouse returns no metadata, the session doesn't exist or isn't ready.
        """
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
