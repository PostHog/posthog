import os
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.tasks.replay_import import (
    _extract_session_id_from_zip_name,
    _parse_clickhouse_json,
    _read_s3_prefix,
    _transform_session_replay_row,
    process_replay_import,
)


class TestExtractSessionIdFromZipName:
    @parameterized.expand(
        [
            ("0083a954-c003-4e80-a10a-7e096a8d218c.zip", "0083a954-c003-4e80-a10a-7e096a8d218c"),
            ("/path/to/0083a954-c003-4e80-a10a-7e096a8d218c.zip", "0083a954-c003-4e80-a10a-7e096a8d218c"),
            ("abc123.zip", "abc123"),
        ]
    )
    def test_extracts_session_id(self, zip_path: str, expected: str) -> None:
        assert _extract_session_id_from_zip_name(zip_path) == expected


class TestParseClickhouseJson:
    def test_parses_meta_and_data_format(self) -> None:
        content = {
            "meta": [{"name": "col1", "type": "String"}, {"name": "col2", "type": "Int64"}],
            "data": [{"col1": "value1", "col2": 42}, {"col1": "value2", "col2": 100}],
        }

        result = _parse_clickhouse_json(json.dumps(content))

        assert result == [{"col1": "value1", "col2": 42}, {"col1": "value2", "col2": 100}]

    def test_parses_plain_array_format(self) -> None:
        content = [{"col1": "value1"}, {"col1": "value2"}]

        result = _parse_clickhouse_json(json.dumps(content))

        assert result == [{"col1": "value1"}, {"col1": "value2"}]

    def test_returns_empty_list_for_empty_data(self) -> None:
        content = {"meta": [{"name": "col1", "type": "String"}], "data": []}

        result = _parse_clickhouse_json(json.dumps(content))

        assert result == []


class TestTransformSessionReplayRow:
    def test_transforms_aggregated_columns_to_raw(self) -> None:
        row = {
            "any(distinct_id)": "user123",
            "start_time": "2025-11-27 14:48:26.424000",
            "end_time": "2025-11-27 15:21:56.908000",
            "first_url": "http://localhost:8010/project/1/replay/home",
            "sum(click_count)": 13,
            "sum(keypress_count)": 86,
            "sum(mouse_activity_count)": 204,
            "active_seconds": 117.982,
            "console_log_count": 35,
            "console_warn_count": 0,
            "console_error_count": 9,
            "snapshot_source": "web",
            "block_first_timestamps": ["2025-11-27 14:48:26.424000"],
            "block_last_timestamps": ["2025-11-27 15:21:56.908000"],
            "block_urls": ["s3://posthog/session_recordings/30d/123-abc"],
            "retention_period_days": 30,
        }

        result = _transform_session_replay_row(row, session_id="test-session", team_id=1)

        assert result["session_id"] == "test-session"
        assert result["team_id"] == 1
        assert result["distinct_id"] == "user123"
        assert result["min_first_timestamp"] == datetime(2025, 11, 27, 14, 48, 26, 424000)
        assert result["max_last_timestamp"] == datetime(2025, 11, 27, 15, 21, 56, 908000)
        assert result["first_url"] == "http://localhost:8010/project/1/replay/home"
        assert result["click_count"] == 13
        assert result["keypress_count"] == 86
        assert result["mouse_activity_count"] == 204
        assert result["active_milliseconds"] == 117982
        assert result["console_log_count"] == 35
        assert result["console_warn_count"] == 0
        assert result["console_error_count"] == 9
        assert result["snapshot_source"] == "web"
        assert result["retention_period_days"] == 30


class TestReadS3Prefix:
    def test_reads_prefix_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix_file = Path(tmpdir) / "s3_prefix.txt"
            prefix_file.write_text("session_recordings/30d")

            result = _read_s3_prefix(Path(tmpdir))

            assert result == "session_recordings/30d"

    def test_returns_none_if_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _read_s3_prefix(Path(tmpdir))

            assert result is None


class TestProcessReplayImport:
    @pytest.fixture
    def sample_export_zip(self) -> str:
        tmpdir = tempfile.mkdtemp()
        export_dir = Path(tmpdir) / "export"
        export_dir.mkdir()

        (export_dir / "s3_prefix.txt").write_text("session_recordings/30d")

        clickhouse_dir = export_dir / "clickhouse"
        clickhouse_dir.mkdir()

        session_replay_data = {
            "meta": [
                {"name": "any(distinct_id)", "type": "String"},
                {"name": "start_time", "type": "DateTime64(6, 'UTC')"},
                {"name": "end_time", "type": "DateTime64(6, 'UTC')"},
                {"name": "duration", "type": "Int64"},
                {"name": "first_url", "type": "Nullable(String)"},
                {"name": "sum(click_count)", "type": "Int64"},
                {"name": "sum(keypress_count)", "type": "Int64"},
                {"name": "sum(mouse_activity_count)", "type": "Int64"},
                {"name": "active_seconds", "type": "Float64"},
                {"name": "console_log_count", "type": "Int64"},
                {"name": "console_warn_count", "type": "Int64"},
                {"name": "console_error_count", "type": "Int64"},
                {"name": "snapshot_source", "type": "Nullable(String)"},
                {"name": "block_first_timestamps", "type": "Array(DateTime64(6, 'UTC'))"},
                {"name": "block_last_timestamps", "type": "Array(DateTime64(6, 'UTC'))"},
                {"name": "block_urls", "type": "Array(String)"},
                {"name": "retention_period_days", "type": "Nullable(Int64)"},
            ],
            "data": [
                {
                    "any(distinct_id)": "user123",
                    "start_time": "2025-11-27 14:48:26.424000",
                    "end_time": "2025-11-27 15:21:56.908000",
                    "duration": 2010,
                    "first_url": "http://localhost:8010/",
                    "sum(click_count)": 13,
                    "sum(keypress_count)": 86,
                    "sum(mouse_activity_count)": 204,
                    "active_seconds": 117.982,
                    "console_log_count": 35,
                    "console_warn_count": 0,
                    "console_error_count": 9,
                    "snapshot_source": "web",
                    "block_first_timestamps": ["2025-11-27 14:48:26.424000"],
                    "block_last_timestamps": ["2025-11-27 15:21:56.908000"],
                    "block_urls": ["s3://posthog/session_recordings/30d/123-abc?range=bytes=0-1000"],
                    "retention_period_days": 30,
                }
            ],
        }
        (clickhouse_dir / "session-replay-events.json").write_text(json.dumps(session_replay_data))

        events_data = {
            "meta": [
                {"name": "uuid", "type": "UUID"},
                {"name": "event", "type": "String"},
                {"name": "properties", "type": "String"},
                {"name": "timestamp", "type": "DateTime64(6, 'UTC')"},
                {"name": "distinct_id", "type": "String"},
            ],
            "data": [
                {
                    "uuid": "019ac5f6-f0e5-7fcc-b32c-e48b1b64477b",
                    "event": "$pageview",
                    "properties": "{}",
                    "timestamp": "2025-11-27 14:48:26.424000",
                    "distinct_id": "user123",
                }
            ],
        }
        (clickhouse_dir / "events.json").write_text(json.dumps(events_data))

        data_dir = export_dir / "data"
        data_dir.mkdir()
        (data_dir / "123-abc").write_bytes(b"fake block data")

        zip_path = Path(tmpdir) / "test-session-id.zip"
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", export_dir)

        yield str(zip_path)

        shutil.rmtree(tmpdir)

    @patch("posthog.tasks.replay_import.object_storage")
    @patch("posthog.tasks.replay_import.sync_execute")
    def test_uploads_s3_files_with_correct_path(
        self, mock_sync_execute: MagicMock, mock_object_storage: MagicMock, sample_export_zip: str
    ) -> None:
        process_replay_import(team_id=42, zip_file_path=sample_export_zip, triggered_by="test")

        mock_object_storage.write.assert_called()
        call_args = mock_object_storage.write.call_args_list[0]
        s3_key = call_args[0][0]
        assert s3_key == "session_recordings/30d/team_42/test-session-id/123-abc"

    @patch("posthog.tasks.replay_import.object_storage")
    @patch("posthog.tasks.replay_import.sync_execute")
    def test_transforms_block_urls_to_new_team(
        self, mock_sync_execute: MagicMock, mock_object_storage: MagicMock, sample_export_zip: str
    ) -> None:
        process_replay_import(team_id=42, zip_file_path=sample_export_zip, triggered_by="test")

        insert_calls = [c for c in mock_sync_execute.call_args_list if "INSERT INTO" in str(c)]
        assert len(insert_calls) >= 1

    @patch("posthog.tasks.replay_import.object_storage")
    @patch("posthog.tasks.replay_import.sync_execute")
    def test_cleans_up_zip_file_after_processing(
        self, mock_sync_execute: MagicMock, mock_object_storage: MagicMock, sample_export_zip: str
    ) -> None:
        process_replay_import(team_id=42, zip_file_path=sample_export_zip, triggered_by="test")

        assert not os.path.exists(sample_export_zip)
