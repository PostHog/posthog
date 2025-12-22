import json
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.temporal.import_recording.activities import (
    build_import_context,
    cleanup_import_data,
    import_event_clickhouse_rows,
    import_recording_data,
    import_replay_clickhouse_rows,
)
from posthog.temporal.import_recording.types import ImportContext, ImportRecordingInput


@pytest.mark.asyncio
async def test_build_import_context_success(tmp_path):
    zip_path = tmp_path / "export.zip"
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()

    clickhouse_dir = extract_dir / "clickhouse"
    clickhouse_dir.mkdir()

    (extract_dir / "s3_prefix.txt").write_text("team/123/session/abc")
    (clickhouse_dir / "session-replay-events.json").write_text(
        json.dumps({"data": [{"team_id": 123, "session_id": "abc"}]})
    )

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(extract_dir / "s3_prefix.txt", "s3_prefix.txt")
        zf.write(clickhouse_dir / "session-replay-events.json", "clickhouse/session-replay-events.json")

    input = ImportRecordingInput(team_id=123, export_file=str(zip_path))

    result = await build_import_context(input)

    assert result.team_id == 123
    assert result.s3_prefix == "team/123/session/abc"
    assert result.session_id == "abc"
    assert result.import_id is not None


@pytest.mark.asyncio
async def test_build_import_context_zip_not_exists():
    input = ImportRecordingInput(team_id=123, export_file="/nonexistent/export.zip")

    with pytest.raises(RuntimeError, match="Zip file does not exist"):
        await build_import_context(input)


@pytest.mark.asyncio
async def test_import_recording_data_success(tmp_path):
    import_id = uuid4()
    import_dir = tmp_path / str(import_id)
    data_dir = import_dir / "data"
    data_dir.mkdir(parents=True)

    (data_dir / "file1.json").write_text("content1")
    (data_dir / "file2.json").write_text("content2")

    context = ImportContext(
        team_id=123,
        import_id=import_id,
        s3_prefix="team/123/session/abc",
        session_id="abc",
    )

    mock_storage = AsyncMock()
    mock_storage.upload_file = AsyncMock()

    with (
        patch(
            "posthog.temporal.import_recording.activities.session_recording_v2_object_storage.async_client"
        ) as mock_storage_client,
        patch("posthog.temporal.import_recording.activities.Path") as mock_path_cls,
    ):
        mock_storage_client.return_value.__aenter__.return_value = mock_storage

        def path_side_effect(p):
            if p == "/tmp":
                return tmp_path
            return Path(p)

        mock_path_cls.side_effect = path_side_effect

        await import_recording_data(context)

    assert mock_storage.upload_file.call_count == 2


@pytest.mark.asyncio
async def test_import_replay_clickhouse_rows_success(tmp_path):
    import_id = uuid4()
    import_dir = tmp_path / str(import_id)
    clickhouse_dir = import_dir / "clickhouse"
    clickhouse_dir.mkdir(parents=True)

    replay_data = {
        "data": [
            {
                "team_id": 123,
                "session_id": "abc",
                "distinct_id": "user1",
                "start_time": "2024-01-01 00:00:00.000000",
                "end_time": "2024-01-01 01:00:00.000000",
                "first_url": "https://example.com",
                "click_count": 10,
                "keypress_count": 5,
                "mouse_activity_count": 100,
                "active_seconds": 3600,
                "console_log_count": 1,
                "console_warn_count": 0,
                "console_error_count": 0,
                "size": 1024,
                "event_count": 50,
                "message_count": 25,
                "snapshot_source": "web",
                "retention_period_days": 30,
                "block_first_timestamps": [],
                "block_last_timestamps": [],
                "block_urls": [],
            },
        ]
    }
    (clickhouse_dir / "session-replay-events.json").write_text(json.dumps(replay_data))

    context = ImportContext(
        team_id=123,
        import_id=import_id,
        s3_prefix="team/123/session/abc",
        session_id="abc",
    )

    mock_client = MagicMock()
    mock_client.execute_query = AsyncMock()

    with (
        patch("posthog.temporal.import_recording.activities.get_client") as mock_get_client,
        patch("posthog.temporal.import_recording.activities.Path") as mock_path_cls,
    ):
        mock_get_client.return_value.__aenter__.return_value = mock_client

        def path_side_effect(p):
            if p == "/tmp":
                return tmp_path
            return Path(p)

        mock_path_cls.side_effect = path_side_effect

        await import_replay_clickhouse_rows(context)

    mock_client.execute_query.assert_called_once()


@pytest.mark.asyncio
async def test_import_event_clickhouse_rows_success(tmp_path):
    import_id = uuid4()
    import_dir = tmp_path / str(import_id)
    clickhouse_dir = import_dir / "clickhouse"
    clickhouse_dir.mkdir(parents=True)

    base_event = {
        "uuid": "uuid1",
        "event": "click",
        "properties": "{}",
        "timestamp": "2024-01-01 00:00:00.000000",
        "team_id": 123,
        "distinct_id": "user1",
        "elements_chain": "",
        "created_at": "2024-01-01 00:00:00.000000",
        "person_id": "00000000-0000-0000-0000-000000000000",
        "person_created_at": "2024-01-01 00:00:00",
        "person_properties": "{}",
        "group0_properties": "{}",
        "group1_properties": "{}",
        "group2_properties": "{}",
        "group3_properties": "{}",
        "group4_properties": "{}",
        "group0_created_at": "1970-01-01 00:00:00",
        "group1_created_at": "1970-01-01 00:00:00",
        "group2_created_at": "1970-01-01 00:00:00",
        "group3_created_at": "1970-01-01 00:00:00",
        "group4_created_at": "1970-01-01 00:00:00",
        "person_mode": "full",
    }
    events_data = {
        "data": [
            base_event,
            {**base_event, "uuid": "uuid2", "event": "pageview"},
        ]
    }
    (clickhouse_dir / "events.json").write_text(json.dumps(events_data))

    context = ImportContext(
        team_id=123,
        import_id=import_id,
        s3_prefix="team/123/session/abc",
        session_id="abc",
    )

    mock_client = MagicMock()
    mock_client.execute_query = AsyncMock()

    with (
        patch("posthog.temporal.import_recording.activities.get_client") as mock_get_client,
        patch("posthog.temporal.import_recording.activities.Path") as mock_path_cls,
    ):
        mock_get_client.return_value.__aenter__.return_value = mock_client

        def path_side_effect(p):
            if p == "/tmp":
                return tmp_path
            return Path(p)

        mock_path_cls.side_effect = path_side_effect

        await import_event_clickhouse_rows(context)

    assert mock_client.execute_query.call_count == 2


@pytest.mark.asyncio
async def test_import_event_clickhouse_rows_no_file(tmp_path):
    import_id = uuid4()
    import_dir = tmp_path / str(import_id)
    import_dir.mkdir(parents=True)

    context = ImportContext(
        team_id=123,
        import_id=import_id,
        s3_prefix="team/123/session/abc",
        session_id="abc",
    )

    with patch("posthog.temporal.import_recording.activities.Path") as mock_path_cls:

        def path_side_effect(p):
            if p == "/tmp":
                return tmp_path
            return Path(p)

        mock_path_cls.side_effect = path_side_effect

        await import_event_clickhouse_rows(context)


@pytest.mark.asyncio
async def test_cleanup_import_data_success(tmp_path):
    import_id = uuid4()
    import_dir = tmp_path / str(import_id)
    import_dir.mkdir(parents=True)
    (import_dir / "test_file.json").write_text("test content")

    assert import_dir.exists()

    context = ImportContext(
        team_id=123,
        import_id=import_id,
        s3_prefix="team/123/session/abc",
        session_id="abc",
    )

    with patch("posthog.temporal.import_recording.activities.Path") as mock_path_cls:

        def path_side_effect(p):
            if p == "/tmp":
                return tmp_path
            return Path(p)

        mock_path_cls.side_effect = path_side_effect

        await cleanup_import_data(context)

    assert not import_dir.exists()


@pytest.mark.asyncio
async def test_cleanup_import_data_directory_not_exists(tmp_path):
    import_id = uuid4()

    context = ImportContext(
        team_id=123,
        import_id=import_id,
        s3_prefix="team/123/session/abc",
        session_id="abc",
    )

    with patch("posthog.temporal.import_recording.activities.Path") as mock_path_cls:

        def path_side_effect(p):
            if p == "/tmp":
                return tmp_path
            return Path(p)

        mock_path_cls.side_effect = path_side_effect

        await cleanup_import_data(context)
