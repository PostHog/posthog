from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.storage import session_recording_v2_object_storage
from posthog.temporal.export_recording.activities import (
    build_recording_export_context,
    cleanup_export_data,
    export_event_clickhouse_rows,
    export_recording_data,
    export_recording_data_prefix,
    export_replay_clickhouse_rows,
    store_export_data,
)
from posthog.temporal.export_recording.types import ExportContext, ExportRecordingInput


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
    assert result.exported_asset_id == TEST_ASSET_ID
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


@pytest.mark.asyncio
async def test_export_recording_data_prefix_success(tmp_path):
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=456, session_id="test-session", team_id=123)

    mock_block = MagicMock()
    mock_block.url = "s3://bucket/team_id/123/session_id/test-session/data/file.json?range=bytes=0-100"

    mock_recording = MagicMock()

    with (
        patch("posthog.temporal.export_recording.activities.SessionRecording", return_value=mock_recording),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
        patch("posthog.temporal.export_recording.activities.list_blocks") as mock_list_blocks,
        patch("posthog.temporal.export_recording.activities.Path") as mock_path_cls,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        mock_list_blocks.return_value = [mock_block]

        mock_output_path = MagicMock()
        mock_parent = MagicMock()
        mock_output_path.parent = mock_parent
        mock_path_cls.return_value.__truediv__.return_value.__truediv__.return_value = mock_output_path

        await export_recording_data_prefix(export_context)

        mock_output_path.open.assert_called_once_with("w")


@pytest.mark.asyncio
async def test_export_recording_data_prefix_no_blocks():
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=456, session_id="test-session", team_id=123)

    mock_recording = MagicMock()

    with (
        patch("posthog.temporal.export_recording.activities.SessionRecording", return_value=mock_recording),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
        patch("posthog.temporal.export_recording.activities.list_blocks") as mock_list_blocks,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        mock_list_blocks.return_value = []

        result = await export_recording_data_prefix(export_context)

        assert result is None


@pytest.mark.asyncio
async def test_cleanup_export_data_success(tmp_path):
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=456, session_id="test-session", team_id=123)

    export_dir = tmp_path / str(export_id)
    export_dir.mkdir()
    (export_dir / "test_file.json").write_text("test content")
    (export_dir / "subdir").mkdir()
    (export_dir / "subdir" / "nested_file.txt").write_text("nested content")

    zip_path = tmp_path / f"{export_id}.zip"
    zip_path.write_text("fake zip content")

    assert export_dir.exists()
    assert zip_path.exists()

    with patch("posthog.temporal.export_recording.activities.Path") as mock_path_cls:

        def path_side_effect(base):
            if base == "/tmp":
                return tmp_path
            return MagicMock()

        mock_path_cls.side_effect = path_side_effect

        await cleanup_export_data(export_context)

    assert not export_dir.exists()
    assert not zip_path.exists()


@pytest.mark.asyncio
async def test_cleanup_export_data_directory_not_exists():
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=456, session_id="test-session", team_id=123)

    with patch("posthog.temporal.export_recording.activities.Path") as mock_path_cls:
        mock_export_dir = MagicMock()
        mock_export_dir.exists.return_value = False

        mock_zip_path = MagicMock()
        mock_zip_path.exists.return_value = False

        def truediv_side_effect(path):
            if ".zip" in str(path):
                return mock_zip_path
            return mock_export_dir

        mock_tmp_path = MagicMock()
        mock_tmp_path.__truediv__ = MagicMock(side_effect=truediv_side_effect)
        mock_path_cls.return_value = mock_tmp_path

        await cleanup_export_data(export_context)


@pytest.mark.asyncio
async def test_store_export_data_success(tmp_path):
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=789, session_id="test-session", team_id=123)

    export_dir = tmp_path / str(export_id)
    export_dir.mkdir()
    (export_dir / "test_file.json").write_text("test content")

    mock_asset = MagicMock()
    mock_storage = AsyncMock()

    with (
        patch("posthog.temporal.export_recording.activities.Path") as mock_path_cls,
        patch("posthog.temporal.export_recording.activities.shutil.make_archive") as mock_make_archive,
        patch(
            "posthog.temporal.export_recording.activities.session_recording_v2_object_storage.async_client"
        ) as mock_storage_client,
        patch("posthog.temporal.export_recording.activities.ExportedAsset.objects") as mock_asset_qs,
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
    ):
        mock_export_dir = MagicMock()
        mock_export_dir.exists.return_value = True
        mock_zip_path = MagicMock()
        mock_zip_path.with_suffix.return_value = tmp_path / f"{export_id}"

        mock_path_cls.return_value.__truediv__.side_effect = [mock_export_dir, mock_zip_path]

        mock_storage_client.return_value.__aenter__.return_value = mock_storage

        mock_asset_qs.aget = AsyncMock(return_value=mock_asset)
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())

        await store_export_data(export_context)

        mock_make_archive.assert_called_once()
        mock_storage.upload_file.assert_called_once()
        mock_asset_qs.aget.assert_called_once_with(pk=789)


@pytest.mark.asyncio
async def test_store_export_data_directory_not_exists():
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=789, session_id="test-session", team_id=123)

    with patch("posthog.temporal.export_recording.activities.Path") as mock_path_cls:
        mock_export_dir = MagicMock()
        mock_export_dir.exists.return_value = False
        mock_path_cls.return_value.__truediv__.return_value = mock_export_dir

        with pytest.raises(RuntimeError, match="Export directory .* does not exist"):
            await store_export_data(export_context)


@pytest.mark.asyncio
async def test_store_export_data_s3_upload_failure():
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=789, session_id="test-session", team_id=123)

    mock_storage = AsyncMock()
    mock_storage.upload_file.side_effect = session_recording_v2_object_storage.FileUploadError("Upload failed")

    with (
        patch("posthog.temporal.export_recording.activities.Path") as mock_path_cls,
        patch("posthog.temporal.export_recording.activities.shutil.make_archive"),
        patch(
            "posthog.temporal.export_recording.activities.session_recording_v2_object_storage.async_client"
        ) as mock_storage_client,
    ):
        mock_export_dir = MagicMock()
        mock_export_dir.exists.return_value = True
        mock_zip_path = MagicMock()

        mock_path_cls.return_value.__truediv__.side_effect = [mock_export_dir, mock_zip_path]
        mock_storage_client.return_value.__aenter__.return_value = mock_storage

        with pytest.raises(session_recording_v2_object_storage.FileUploadError):
            await store_export_data(export_context)


@pytest.mark.asyncio
async def test_export_replay_clickhouse_rows_success():
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=456, session_id="test-session", team_id=123)

    mock_ch_response = MagicMock()
    mock_ch_response.content.read = AsyncMock(return_value=b'{"data": []}')

    mock_query_ctx = MagicMock()
    mock_query_ctx.__aenter__ = AsyncMock(return_value=mock_ch_response)
    mock_query_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.aget_query.return_value = mock_query_ctx

    with (
        patch("posthog.temporal.export_recording.activities.get_client") as mock_get_client,
        patch("posthog.temporal.export_recording.activities.SessionReplayEvents.get_metadata_query") as mock_query,
        patch("posthog.temporal.export_recording.activities.Path") as mock_path_cls,
    ):
        mock_get_client.return_value.__aenter__.return_value = mock_client
        mock_query.return_value = "SELECT * FROM session_replay_events"

        mock_output_path = MagicMock()
        mock_parent = MagicMock()
        mock_output_path.parent = mock_parent
        mock_path_cls.return_value.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value = (
            mock_output_path
        )

        await export_replay_clickhouse_rows(export_context)

        mock_client.aget_query.assert_called_once()
        mock_output_path.open.assert_called_once_with("wb")


@pytest.mark.asyncio
async def test_export_event_clickhouse_rows_success():
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=456, session_id="test-session", team_id=123)

    mock_ch_response = MagicMock()
    mock_ch_response.content.read = AsyncMock(return_value=b'{"data": []}')

    mock_query_ctx = MagicMock()
    mock_query_ctx.__aenter__ = AsyncMock(return_value=mock_ch_response)
    mock_query_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.aget_query.return_value = mock_query_ctx

    with (
        patch("posthog.temporal.export_recording.activities.get_client") as mock_get_client,
        patch("posthog.temporal.export_recording.activities.Path") as mock_path_cls,
    ):
        mock_get_client.return_value.__aenter__.return_value = mock_client

        mock_output_path = MagicMock()
        mock_parent = MagicMock()
        mock_output_path.parent = mock_parent
        mock_path_cls.return_value.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value = (
            mock_output_path
        )

        await export_event_clickhouse_rows(export_context)

        mock_client.aget_query.assert_called_once()
        mock_output_path.open.assert_called_once_with("wb")


@pytest.mark.asyncio
async def test_export_recording_data_success():
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=456, session_id="test-session", team_id=123)

    mock_block = MagicMock()
    mock_block.url = "s3://bucket/team/123/session/test-session/data/file.json?range=bytes=100-200"

    mock_recording = MagicMock()
    mock_storage = AsyncMock()
    mock_storage.fetch_block_bytes = AsyncMock(return_value=b"block data content")

    with (
        patch("posthog.temporal.export_recording.activities.SessionRecording", return_value=mock_recording),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
        patch("posthog.temporal.export_recording.activities.list_blocks") as mock_list_blocks,
        patch(
            "posthog.temporal.export_recording.activities.session_recording_v2_object_storage.async_client"
        ) as mock_storage_client,
        patch("posthog.temporal.export_recording.activities.Path") as mock_path_cls,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        mock_list_blocks.return_value = [mock_block]
        mock_storage_client.return_value.__aenter__.return_value = mock_storage

        mock_output_path = MagicMock()
        mock_parent = MagicMock()
        mock_output_path.parent = mock_parent
        mock_path_cls.return_value.__truediv__.return_value.__truediv__.return_value.__truediv__.return_value = (
            mock_output_path
        )

        await export_recording_data(export_context)

        mock_storage.fetch_block_bytes.assert_called_once_with(mock_block.url)
        mock_output_path.open.assert_called_once_with("wb")


@pytest.mark.asyncio
async def test_export_recording_data_no_blocks():
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=456, session_id="test-session", team_id=123)

    mock_recording = MagicMock()

    with (
        patch("posthog.temporal.export_recording.activities.SessionRecording", return_value=mock_recording),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
        patch("posthog.temporal.export_recording.activities.list_blocks") as mock_list_blocks,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        mock_list_blocks.return_value = []

        await export_recording_data(export_context)


@pytest.mark.asyncio
async def test_export_recording_data_malformed_url():
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=456, session_id="test-session", team_id=123)

    mock_block = MagicMock()
    mock_block.url = "s3://bucket/team/123/session/test-session/data/file.json?invalid_query"

    mock_recording = MagicMock()

    with (
        patch("posthog.temporal.export_recording.activities.SessionRecording", return_value=mock_recording),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
        patch("posthog.temporal.export_recording.activities.list_blocks") as mock_list_blocks,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        mock_list_blocks.return_value = [mock_block]

        await export_recording_data(export_context)


@pytest.mark.asyncio
async def test_export_recording_data_block_fetch_error():
    export_id = uuid4()
    export_context = ExportContext(export_id=export_id, exported_asset_id=456, session_id="test-session", team_id=123)

    mock_block = MagicMock()
    mock_block.url = "s3://bucket/team/123/session/test-session/data/file.json?range=bytes=100-200"

    mock_recording = MagicMock()
    mock_storage = AsyncMock()
    mock_storage.fetch_block_bytes = AsyncMock(
        side_effect=session_recording_v2_object_storage.BlockFetchError("Fetch failed")
    )

    with (
        patch("posthog.temporal.export_recording.activities.SessionRecording", return_value=mock_recording),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
        patch("posthog.temporal.export_recording.activities.list_blocks") as mock_list_blocks,
        patch(
            "posthog.temporal.export_recording.activities.session_recording_v2_object_storage.async_client"
        ) as mock_storage_client,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        mock_list_blocks.return_value = [mock_block]
        mock_storage_client.return_value.__aenter__.return_value = mock_storage

        await export_recording_data(export_context)
