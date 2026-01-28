import json
import base64
from uuid import UUID, uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.models.exported_recording import ExportedRecording
from posthog.storage import session_recording_v2_object_storage
from posthog.temporal.export_recording.activities import (
    _redis_key,
    _redis_url,
    build_recording_export_context,
    cleanup_export_data,
    export_event_clickhouse_rows,
    export_recording_data,
    export_recording_data_prefix,
    export_replay_clickhouse_rows,
    store_export_data,
)
from posthog.temporal.export_recording.types import ExportContext, ExportRecordingInput, RedisConfig

TEST_RECORDING_ID = UUID("01938a67-1234-7000-8000-000000000001")
TEST_REDIS_CONFIG = RedisConfig(redis_url="redis://test-redis:6379", redis_ttl=3600)


def test_redis_url_with_custom_url():
    config = RedisConfig(redis_url="redis://my-redis:6380")
    assert _redis_url(config) == "redis://my-redis:6380"


def test_redis_url_with_default_uses_settings():
    config = RedisConfig()
    with patch("posthog.temporal.export_recording.activities.settings") as mock_settings:
        mock_settings.SESSION_RECORDING_REDIS_URL = "redis://settings-redis:6379"
        assert _redis_url(config) == "redis://settings-redis:6379"


def test_redis_key_without_suffix():
    export_id = UUID("01938a67-1234-7000-8000-000000000001")
    key = _redis_key(export_id, "replay-events")
    assert key == f"export-recording:{export_id}:replay-events"


def test_redis_key_with_suffix():
    export_id = UUID("01938a67-1234-7000-8000-000000000001")
    key = _redis_key(export_id, "block", "file.json")
    assert key == f"export-recording:{export_id}:block:file.json"


@pytest.mark.asyncio
async def test_build_recording_export_context_success():
    TEST_SESSION_ID = "test-session-123"
    TEST_TEAM_ID = 67890

    mock_team = MagicMock()
    mock_team.id = TEST_TEAM_ID

    mock_record = MagicMock()
    mock_record.team = mock_team
    mock_record.session_id = TEST_SESSION_ID
    mock_record.status = ExportedRecording.Status.PENDING
    mock_record.save = MagicMock()

    mock_qs = MagicMock()
    mock_qs.select_related.return_value.only.return_value.aget = AsyncMock(return_value=mock_record)

    with (
        patch("posthog.temporal.export_recording.activities.ExportedRecording.objects", mock_qs),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        result = await build_recording_export_context(
            ExportRecordingInput(exported_recording_id=TEST_RECORDING_ID, redis_config=TEST_REDIS_CONFIG)
        )

    assert result.session_id == TEST_SESSION_ID
    assert result.team_id == TEST_TEAM_ID
    assert result.exported_recording_id == TEST_RECORDING_ID
    assert result.redis_config == TEST_REDIS_CONFIG
    mock_qs.select_related.assert_called_once_with("team")
    mock_qs.select_related.return_value.only.assert_called_once_with("status", "session_id", "team__id")
    mock_qs.select_related.return_value.only.return_value.aget.assert_called_once_with(id=TEST_RECORDING_ID)


@pytest.mark.asyncio
async def test_export_replay_clickhouse_rows_success():
    export_id = uuid4()
    export_context = ExportContext(
        export_id=export_id,
        exported_recording_id=TEST_RECORDING_ID,
        session_id="test-session",
        team_id=123,
        redis_config=TEST_REDIS_CONFIG,
    )

    mock_ch_response = MagicMock()
    mock_ch_response.content.read = AsyncMock(return_value=b'{"data": []}')

    mock_query_ctx = MagicMock()
    mock_query_ctx.__aenter__ = AsyncMock(return_value=mock_ch_response)
    mock_query_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.aget_query.return_value = mock_query_ctx

    mock_redis = AsyncMock()

    with (
        patch("posthog.temporal.export_recording.activities.get_client") as mock_get_client,
        patch("posthog.temporal.export_recording.activities.SessionReplayEvents.get_metadata_query") as mock_query,
        patch("posthog.temporal.export_recording.activities.get_async_client") as mock_get_async_client,
    ):
        mock_get_client.return_value.__aenter__.return_value = mock_client
        mock_query.return_value = "SELECT * FROM session_replay_events"
        mock_get_async_client.return_value = mock_redis

        await export_replay_clickhouse_rows(export_context)

        mock_client.aget_query.assert_called_once()
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == _redis_key(export_id, "replay-events")
        assert call_args[0][1] == TEST_REDIS_CONFIG.redis_ttl
        assert call_args[0][2] == b'{"data": []}'


@pytest.mark.asyncio
async def test_export_event_clickhouse_rows_success():
    export_id = uuid4()
    export_context = ExportContext(
        export_id=export_id,
        exported_recording_id=TEST_RECORDING_ID,
        session_id="test-session",
        team_id=123,
        redis_config=TEST_REDIS_CONFIG,
    )

    mock_ch_response = MagicMock()
    mock_ch_response.content.read = AsyncMock(return_value=b'{"data": []}')

    mock_query_ctx = MagicMock()
    mock_query_ctx.__aenter__ = AsyncMock(return_value=mock_ch_response)
    mock_query_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.aget_query.return_value = mock_query_ctx

    mock_redis = AsyncMock()

    with (
        patch("posthog.temporal.export_recording.activities.get_client") as mock_get_client,
        patch("posthog.temporal.export_recording.activities.get_async_client") as mock_get_async_client,
    ):
        mock_get_client.return_value.__aenter__.return_value = mock_client
        mock_get_async_client.return_value = mock_redis

        await export_event_clickhouse_rows(export_context)

        mock_client.aget_query.assert_called_once()
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == _redis_key(export_id, "events")
        assert call_args[0][1] == TEST_REDIS_CONFIG.redis_ttl


@pytest.mark.asyncio
async def test_export_recording_data_prefix_success():
    export_id = uuid4()
    export_context = ExportContext(
        export_id=export_id,
        exported_recording_id=TEST_RECORDING_ID,
        session_id="test-session",
        team_id=123,
        redis_config=TEST_REDIS_CONFIG,
    )

    mock_block = MagicMock()
    mock_block.url = "s3://bucket/team_id/123/session_id/test-session/data/file.json?range=bytes=0-100"

    mock_recording = MagicMock()
    mock_redis = AsyncMock()

    with (
        patch("posthog.temporal.export_recording.activities.SessionRecording", return_value=mock_recording),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
        patch("posthog.temporal.export_recording.activities.list_blocks") as mock_list_blocks,
        patch("posthog.temporal.export_recording.activities.get_async_client") as mock_get_async_client,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        mock_list_blocks.return_value = [mock_block]
        mock_get_async_client.return_value = mock_redis

        await export_recording_data_prefix(export_context)

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == _redis_key(export_id, "s3-prefix")
        assert call_args[0][1] == TEST_REDIS_CONFIG.redis_ttl
        assert call_args[0][2] == "team_id/123/session_id/test-session/data"


@pytest.mark.asyncio
async def test_export_recording_data_prefix_no_blocks():
    export_id = uuid4()
    export_context = ExportContext(
        export_id=export_id,
        exported_recording_id=TEST_RECORDING_ID,
        session_id="test-session",
        team_id=123,
        redis_config=TEST_REDIS_CONFIG,
    )

    mock_recording = MagicMock()

    with (
        patch("posthog.temporal.export_recording.activities.SessionRecording", return_value=mock_recording),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
        patch("posthog.temporal.export_recording.activities.list_blocks") as mock_list_blocks,
        patch("posthog.temporal.export_recording.activities.get_async_client") as mock_get_async_client,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        mock_list_blocks.return_value = []

        await export_recording_data_prefix(export_context)

        mock_get_async_client.assert_not_called()


@pytest.mark.asyncio
async def test_export_recording_data_success():
    export_id = uuid4()
    export_context = ExportContext(
        export_id=export_id,
        exported_recording_id=TEST_RECORDING_ID,
        session_id="test-session",
        team_id=123,
        redis_config=TEST_REDIS_CONFIG,
    )

    mock_block = MagicMock()
    mock_block.url = "s3://bucket/team/123/session/test-session/data/file.json?range=bytes=100-200"

    mock_recording = MagicMock()
    mock_storage = AsyncMock()
    mock_storage.fetch_block_bytes = AsyncMock(return_value=b"block data content")
    mock_redis = AsyncMock()

    with (
        patch("posthog.temporal.export_recording.activities.SessionRecording", return_value=mock_recording),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
        patch("posthog.temporal.export_recording.activities.list_blocks") as mock_list_blocks,
        patch(
            "posthog.temporal.export_recording.activities.session_recording_v2_object_storage.async_client"
        ) as mock_storage_client,
        patch("posthog.temporal.export_recording.activities.get_async_client") as mock_get_async_client,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        mock_list_blocks.return_value = [mock_block]
        mock_storage_client.return_value.__aenter__.return_value = mock_storage
        mock_get_async_client.return_value = mock_redis

        await export_recording_data(export_context)

        mock_storage.fetch_block_bytes.assert_called_once_with(mock_block.url)
        assert mock_redis.setex.call_count == 2

        block_call = mock_redis.setex.call_args_list[0]
        assert block_call[0][0] == _redis_key(export_id, "block", "file.json")
        assert block_call[0][2] == base64.b64encode(b"block data content").decode("utf-8")

        manifest_call = mock_redis.setex.call_args_list[1]
        assert manifest_call[0][0] == _redis_key(export_id, "block-manifest")
        manifest_data = json.loads(manifest_call[0][2])
        assert len(manifest_data) == 1
        assert manifest_data[0]["filename"] == "file.json"
        assert manifest_data[0]["offset"] == 100


@pytest.mark.asyncio
async def test_export_recording_data_no_blocks():
    export_id = uuid4()
    export_context = ExportContext(
        export_id=export_id,
        exported_recording_id=TEST_RECORDING_ID,
        session_id="test-session",
        team_id=123,
        redis_config=TEST_REDIS_CONFIG,
    )

    mock_recording = MagicMock()
    mock_redis = AsyncMock()

    with (
        patch("posthog.temporal.export_recording.activities.SessionRecording", return_value=mock_recording),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
        patch("posthog.temporal.export_recording.activities.list_blocks") as mock_list_blocks,
        patch("posthog.temporal.export_recording.activities.get_async_client") as mock_get_async_client,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        mock_list_blocks.return_value = []
        mock_get_async_client.return_value = mock_redis

        await export_recording_data(export_context)

        mock_redis.setex.assert_called_once()
        manifest_call = mock_redis.setex.call_args
        assert manifest_call[0][0] == _redis_key(export_id, "block-manifest")
        assert json.loads(manifest_call[0][2]) == []


@pytest.mark.asyncio
async def test_export_recording_data_malformed_url():
    export_id = uuid4()
    export_context = ExportContext(
        export_id=export_id,
        exported_recording_id=TEST_RECORDING_ID,
        session_id="test-session",
        team_id=123,
        redis_config=TEST_REDIS_CONFIG,
    )

    mock_block = MagicMock()
    mock_block.url = "s3://bucket/team/123/session/test-session/data/file.json?invalid_query"

    mock_recording = MagicMock()
    mock_redis = AsyncMock()

    with (
        patch("posthog.temporal.export_recording.activities.SessionRecording", return_value=mock_recording),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
        patch("posthog.temporal.export_recording.activities.list_blocks") as mock_list_blocks,
        patch("posthog.temporal.export_recording.activities.get_async_client") as mock_get_async_client,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        mock_list_blocks.return_value = [mock_block]
        mock_get_async_client.return_value = mock_redis

        await export_recording_data(export_context)

        mock_redis.setex.assert_called_once()
        manifest_call = mock_redis.setex.call_args
        assert json.loads(manifest_call[0][2]) == []


@pytest.mark.asyncio
async def test_export_recording_data_block_fetch_error():
    export_id = uuid4()
    export_context = ExportContext(
        export_id=export_id,
        exported_recording_id=TEST_RECORDING_ID,
        session_id="test-session",
        team_id=123,
        redis_config=TEST_REDIS_CONFIG,
    )

    mock_block = MagicMock()
    mock_block.url = "s3://bucket/team/123/session/test-session/data/file.json?range=bytes=100-200"

    mock_recording = MagicMock()
    mock_storage = AsyncMock()
    mock_storage.fetch_block_bytes = AsyncMock(
        side_effect=session_recording_v2_object_storage.BlockFetchError("Fetch failed")
    )
    mock_redis = AsyncMock()

    with (
        patch("posthog.temporal.export_recording.activities.SessionRecording", return_value=mock_recording),
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
        patch("posthog.temporal.export_recording.activities.list_blocks") as mock_list_blocks,
        patch(
            "posthog.temporal.export_recording.activities.session_recording_v2_object_storage.async_client"
        ) as mock_storage_client,
        patch("posthog.temporal.export_recording.activities.get_async_client") as mock_get_async_client,
    ):
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())
        mock_list_blocks.return_value = [mock_block]
        mock_storage_client.return_value.__aenter__.return_value = mock_storage
        mock_get_async_client.return_value = mock_redis

        await export_recording_data(export_context)

        mock_redis.setex.assert_called_once()
        manifest_call = mock_redis.setex.call_args
        assert json.loads(manifest_call[0][2]) == []


@pytest.mark.asyncio
async def test_store_export_data_success(tmp_path):
    export_id = uuid4()
    export_context = ExportContext(
        export_id=export_id,
        exported_recording_id=TEST_RECORDING_ID,
        session_id="test-session",
        team_id=123,
        redis_config=TEST_REDIS_CONFIG,
    )

    block_manifest = [
        {"filename": "file.json", "offset": 100, "redis_key": f"export-recording:{export_id}:block:file.json"}
    ]
    block_data_encoded = base64.b64encode(b"block content").decode("utf-8")

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(
        side_effect=lambda key: {
            _redis_key(export_id, "replay-events"): b'{"data": []}',
            _redis_key(export_id, "events"): b'{"events": []}',
            _redis_key(export_id, "s3-prefix"): "team/123/session",
            _redis_key(export_id, "block-manifest"): json.dumps(block_manifest),
            f"export-recording:{export_id}:block:file.json": block_data_encoded,
        }.get(key)
    )

    mock_record = MagicMock()
    mock_record.save = MagicMock()
    mock_storage = AsyncMock()

    with (
        patch("posthog.temporal.export_recording.activities.get_async_client") as mock_get_async_client,
        patch("posthog.temporal.export_recording.activities.Path") as mock_path_cls,
        patch("posthog.temporal.export_recording.activities.shutil.make_archive") as mock_make_archive,
        patch("posthog.temporal.export_recording.activities.shutil.rmtree"),
        patch(
            "posthog.temporal.export_recording.activities.session_recording_v2_object_storage.async_client"
        ) as mock_storage_client,
        patch("posthog.temporal.export_recording.activities.ExportedRecording.objects") as mock_record_qs,
        patch("posthog.temporal.export_recording.activities.database_sync_to_async") as mock_db_sync,
    ):
        mock_get_async_client.return_value = mock_redis

        mock_export_dir = MagicMock()
        mock_clickhouse_dir = MagicMock()
        mock_data_dir = MagicMock()
        mock_zip_path = MagicMock()
        mock_zip_path.with_suffix.return_value = tmp_path / f"{export_id}"

        def truediv_side_effect(path):
            if str(path) == str(export_id):
                return mock_export_dir
            if ".zip" in str(path):
                return mock_zip_path
            return MagicMock()

        mock_path_cls.return_value.__truediv__ = MagicMock(side_effect=truediv_side_effect)
        mock_export_dir.__truediv__ = MagicMock(
            side_effect=lambda p: mock_clickhouse_dir
            if p == "clickhouse"
            else mock_data_dir
            if p == "data"
            else MagicMock()
        )

        mock_storage_client.return_value.__aenter__.return_value = mock_storage
        mock_record_qs.aget = AsyncMock(return_value=mock_record)
        mock_db_sync.side_effect = lambda fn: AsyncMock(return_value=fn())

        await store_export_data(export_context)

        mock_make_archive.assert_called_once()
        mock_storage.upload_file.assert_called_once()
        mock_record_qs.aget.assert_called_once_with(id=TEST_RECORDING_ID)


@pytest.mark.asyncio
async def test_store_export_data_s3_upload_failure():
    export_id = uuid4()
    export_context = ExportContext(
        export_id=export_id,
        exported_recording_id=TEST_RECORDING_ID,
        session_id="test-session",
        team_id=123,
        redis_config=TEST_REDIS_CONFIG,
    )

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    mock_storage = AsyncMock()
    mock_storage.upload_file.side_effect = session_recording_v2_object_storage.FileUploadError("Upload failed")

    with (
        patch("posthog.temporal.export_recording.activities.get_async_client") as mock_get_async_client,
        patch("posthog.temporal.export_recording.activities.Path") as mock_path_cls,
        patch("posthog.temporal.export_recording.activities.shutil.make_archive"),
        patch(
            "posthog.temporal.export_recording.activities.session_recording_v2_object_storage.async_client"
        ) as mock_storage_client,
    ):
        mock_get_async_client.return_value = mock_redis

        mock_export_dir = MagicMock()
        mock_clickhouse_dir = MagicMock()
        mock_zip_path = MagicMock()

        def truediv_side_effect(path):
            if str(path) == str(export_id):
                return mock_export_dir
            if ".zip" in str(path):
                return mock_zip_path
            return MagicMock()

        mock_path_cls.return_value.__truediv__ = MagicMock(side_effect=truediv_side_effect)
        mock_export_dir.__truediv__ = MagicMock(return_value=mock_clickhouse_dir)
        mock_storage_client.return_value.__aenter__.return_value = mock_storage

        with pytest.raises(session_recording_v2_object_storage.FileUploadError):
            await store_export_data(export_context)


@pytest.mark.asyncio
async def test_cleanup_export_data_success():
    export_id = uuid4()
    export_context = ExportContext(
        export_id=export_id,
        exported_recording_id=TEST_RECORDING_ID,
        session_id="test-session",
        team_id=123,
        redis_config=TEST_REDIS_CONFIG,
    )

    block_manifest = [
        {"filename": "file.json", "offset": 100, "redis_key": f"export-recording:{export_id}:block:file.json"}
    ]

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(block_manifest))
    mock_redis.delete = AsyncMock(return_value=5)

    with patch("posthog.temporal.export_recording.activities.get_async_client") as mock_get_async_client:
        mock_get_async_client.return_value = mock_redis

        await cleanup_export_data(export_context)

        mock_redis.delete.assert_called_once()
        delete_args = mock_redis.delete.call_args[0]
        assert _redis_key(export_id, "replay-events") in delete_args
        assert _redis_key(export_id, "events") in delete_args
        assert _redis_key(export_id, "s3-prefix") in delete_args
        assert _redis_key(export_id, "block-manifest") in delete_args
        assert f"export-recording:{export_id}:block:file.json" in delete_args


@pytest.mark.asyncio
async def test_cleanup_export_data_no_manifest():
    export_id = uuid4()
    export_context = ExportContext(
        export_id=export_id,
        exported_recording_id=TEST_RECORDING_ID,
        session_id="test-session",
        team_id=123,
        redis_config=TEST_REDIS_CONFIG,
    )

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.delete = AsyncMock(return_value=4)

    with patch("posthog.temporal.export_recording.activities.get_async_client") as mock_get_async_client:
        mock_get_async_client.return_value = mock_redis

        await cleanup_export_data(export_context)

        mock_redis.delete.assert_called_once()
        delete_args = mock_redis.delete.call_args[0]
        assert len(delete_args) == 4
