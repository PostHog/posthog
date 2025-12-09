import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.temporal.export_recording.activities import build_recording_export_context
from posthog.temporal.export_recording.types import ExportRecordingInput


@pytest.mark.asyncio
async def test_build_recording_export_context_success():
    TEST_ASSET_ID = 12345
    TEST_SESSION_ID = "test-session-123"
    TEST_TEAM_ID = 67890

    mock_team = MagicMock()
    mock_team.id = TEST_TEAM_ID

    mock_asset = MagicMock()
    mock_asset.team = mock_team
    mock_asset.export_context = {"session_id": TEST_SESSION_ID}

    mock_qs = MagicMock()
    mock_qs.select_related.return_value.aget = AsyncMock(return_value=mock_asset)

    with patch("posthog.temporal.export_recording.activities.ExportedAsset.objects", mock_qs):
        result = await build_recording_export_context(ExportRecordingInput(exported_asset_id=TEST_ASSET_ID))

    assert result.session_id == TEST_SESSION_ID
    assert result.team_id == TEST_TEAM_ID
    mock_qs.select_related.assert_called_once_with("team")
    mock_qs.select_related.return_value.aget.assert_called_once_with(pk=TEST_ASSET_ID)


@pytest.mark.asyncio
async def test_build_recording_export_context_missing_session_id():
    TEST_ASSET_ID = 99999

    mock_team = MagicMock()
    mock_team.id = 11111

    mock_asset = MagicMock()
    mock_asset.team = mock_team
    mock_asset.export_context = {}

    mock_qs = MagicMock()
    mock_qs.select_related.return_value.aget = AsyncMock(return_value=mock_asset)

    with patch("posthog.temporal.export_recording.activities.ExportedAsset.objects", mock_qs):
        with pytest.raises(RuntimeError, match="Malformed asset - must contain session_id"):
            await build_recording_export_context(ExportRecordingInput(exported_asset_id=TEST_ASSET_ID))


@pytest.mark.asyncio
async def test_build_recording_export_context_no_export_context():
    TEST_ASSET_ID = 88888

    mock_team = MagicMock()
    mock_team.id = 22222

    mock_asset = MagicMock()
    mock_asset.team = mock_team
    mock_asset.export_context = None

    mock_qs = MagicMock()
    mock_qs.select_related.return_value.aget = AsyncMock(return_value=mock_asset)

    with patch("posthog.temporal.export_recording.activities.ExportedAsset.objects", mock_qs):
        with pytest.raises(RuntimeError, match="Malformed asset - must contain session_id"):
            await build_recording_export_context(ExportRecordingInput(exported_asset_id=TEST_ASSET_ID))
