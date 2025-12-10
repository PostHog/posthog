import os
import json
import zipfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import parse

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace(" ", "T"))
    except (ValueError, AttributeError):
        return None


def process_replay_import(team_id: int, zip_file_path: str, triggered_by: str) -> None:
    logger.info(
        "import_replay_data_started",
        zip_file_path=zip_file_path,
        triggered_by=triggered_by,
    )

    try:
        with tempfile.TemporaryDirectory() as extract_dir:
            with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)

            extract_path = Path(extract_dir)

            s3_prefix = _read_s3_prefix(extract_path)
            logger.info("import_replay_s3_prefix", s3_prefix=s3_prefix)

            _copy_s3_files(extract_path, s3_prefix)
            _insert_clickhouse_data(team_id, extract_path, s3_prefix)

        logger.info(
            "import_replay_data_completed",
            zip_file_path=zip_file_path,
        )
    finally:
        if os.path.exists(zip_file_path):
            os.unlink(zip_file_path)


def _read_s3_prefix(extract_path: Path) -> str | None:
    prefix_file = extract_path / "s3_prefix.txt"
    if prefix_file.exists():
        return prefix_file.read_text().strip()
    return None


def _parse_clickhouse_json(content: str) -> list[dict[str, Any]]:
    data = json.loads(content)

    if isinstance(data, list):
        return data

    if isinstance(data, dict) and "data" in data:
        return data["data"]

    return []


def _transform_session_replay_row(row: dict[str, Any], team_id: int) -> dict[str, Any]:
    active_seconds = row.get("active_seconds", 0) or 0
    min_first_ts = row.get("start_time") or row.get("min_first_timestamp")
    max_last_ts = row.get("end_time") or row.get("max_last_timestamp")

    return {
        "session_id": row.get("session_id") or row.get("$session_id"),
        "team_id": team_id,
        "distinct_id": row.get("any(distinct_id)") or row.get("distinct_id"),
        "min_first_timestamp": _parse_timestamp(min_first_ts),
        "max_last_timestamp": _parse_timestamp(max_last_ts),
        "first_url": row.get("first_url"),
        "click_count": row.get("sum(click_count)") or row.get("click_count", 0),
        "keypress_count": row.get("sum(keypress_count)") or row.get("keypress_count", 0),
        "mouse_activity_count": row.get("sum(mouse_activity_count)") or row.get("mouse_activity_count", 0),
        "active_milliseconds": int(active_seconds * 1000),
        "console_log_count": row.get("console_log_count", 0),
        "console_warn_count": row.get("console_warn_count", 0),
        "console_error_count": row.get("console_error_count", 0),
        "size": row.get("size", 0),
        "event_count": row.get("event_count", 0),
        "message_count": row.get("message_count", 0),
        "snapshot_source": row.get("snapshot_source"),
        "retention_period_days": row.get("retention_period_days"),
    }


def _transform_block_urls(block_urls: list[str], s3_prefix: str | None) -> list[str]:
    if not s3_prefix:
        raise ValueError("s3_prefix is required to transform block URLs")

    transformed = []
    for url in block_urls:
        _, _, s3_path, _, query, _ = parse.urlparse(url)
        filename = s3_path.split("/")[-1]

        new_path = f"{s3_prefix}/{filename}"
        new_url = f"s3://posthog/{new_path}"
        if query:
            new_url = f"{new_url}?{query}"
        transformed.append(new_url)

    return transformed


def _copy_s3_files(extract_path: Path, s3_prefix: str | None) -> None:
    data_dir = extract_path / "data"
    if not data_dir.exists():
        raise ValueError("data directory not found in extracted data")

    for file_path in data_dir.iterdir():
        if not file_path.is_file():
            raise ValueError(f"Unexpected directory found in data directory: {file_path}")

        filename = file_path.name

        if s3_prefix:
            s3_key = f"{s3_prefix}/{filename}"
        else:
            raise ValueError("s3_prefix is required to copy S3 files")

        with open(file_path, "rb") as f:
            content = f.read()

        object_storage.write(s3_key, content)


def _insert_clickhouse_data(team_id: int, extract_path: Path, s3_prefix: str | None) -> None:
    clickhouse_dir = extract_path / "clickhouse"
    if not clickhouse_dir.exists():
        raise ValueError("clickhouse directory not found in extracted data")

    session_replay_file = clickhouse_dir / "session-replay-events.json"
    if session_replay_file.exists():
        _insert_session_replay_events(session_replay_file, team_id)
    else:
        raise ValueError("session-replay-events.json file not found in clickhouse directory")

    events_file = clickhouse_dir / "events.json"
    if events_file.exists():
        _insert_events(events_file)


def _insert_session_replay_events(json_file: Path, team_id: int) -> None:
    with open(json_file) as f:
        rows = _parse_clickhouse_json(f.read())

    if not rows:
        raise ValueError("No rows found in session-replay-events.json")

    logger.info(
        "import_replay_session_replay_events",
        file=json_file.name,
        row_count=len(rows),
    )

    transformed_rows = []
    for row in rows:
        transformed = _transform_session_replay_row(row, team_id)

        block_urls = row.get("block_urls", [])

        transformed["block_urls"] = block_urls
        transformed["block_first_timestamps"] = [_parse_timestamp(ts) for ts in row.get("block_first_timestamps", [])]
        transformed["block_last_timestamps"] = [_parse_timestamp(ts) for ts in row.get("block_last_timestamps", [])]

        transformed_rows.append(transformed)

    for row in transformed_rows:
        sync_execute(
            """
            INSERT INTO writable_session_replay_events (
                `session_id`,
                team_id,
                distinct_id,
                min_first_timestamp,
                max_last_timestamp,
                first_url,
                click_count,
                keypress_count,
                mouse_activity_count,
                active_milliseconds,
                console_log_count,
                console_warn_count,
                console_error_count,
                size,
                event_count,
                message_count,
                snapshot_source,
                snapshot_library,
                retention_period_days,
                block_first_timestamps,
                block_last_timestamps,
                block_urls
            )
            SELECT
                any(session_id),
                any(team_id),
                any(distinct_id),
                any(min_first_timestamp),
                any(max_last_timestamp),
                argMinState(first_url, min_first_timestamp),
                any(click_count),
                any(keypress_count),
                any(mouse_activity_count),
                any(active_milliseconds),
                any(console_log_count),
                any(console_warn_count),
                any(console_error_count),
                any(size),
                any(event_count),
                any(message_count),
                argMinState(snapshot_source, min_first_timestamp),
                argMinState(snapshot_library, min_first_timestamp),
                any(retention_period_days),
                any(block_first_timestamps),
                any(block_last_timestamps),
                any(block_urls)
            FROM (
                SELECT
                    %(session_id)s as session_id,
                    %(team_id)s as team_id,
                    %(distinct_id)s as distinct_id,
                    CAST(%(min_first_timestamp)s AS DateTime64(6, 'UTC')) as min_first_timestamp,
                    CAST(%(max_last_timestamp)s AS DateTime64(6, 'UTC')) as max_last_timestamp,
                    CAST(%(first_url)s AS Nullable(String)) as first_url,
                    %(click_count)s as click_count,
                    %(keypress_count)s as keypress_count,
                    %(mouse_activity_count)s as mouse_activity_count,
                    %(active_milliseconds)s as active_milliseconds,
                    %(console_log_count)s as console_log_count,
                    %(console_warn_count)s as console_warn_count,
                    %(console_error_count)s as console_error_count,
                    %(size)s as size,
                    %(event_count)s as event_count,
                    %(message_count)s as message_count,
                    CAST(%(snapshot_source)s AS LowCardinality(Nullable(String))) as snapshot_source,
                    CAST(NULL AS Nullable(String)) as snapshot_library,
                    %(retention_period_days)s as retention_period_days,
                    %(block_first_timestamps)s as block_first_timestamps,
                    %(block_last_timestamps)s as block_last_timestamps,
                    %(block_urls)s as block_urls
            )
            """,
            {
                "session_id": row["session_id"],
                "team_id": row["team_id"],
                "distinct_id": row["distinct_id"],
                "min_first_timestamp": row["min_first_timestamp"],
                "max_last_timestamp": row["max_last_timestamp"],
                "first_url": row["first_url"],
                "click_count": row["click_count"],
                "keypress_count": row["keypress_count"],
                "mouse_activity_count": row["mouse_activity_count"],
                "active_milliseconds": row["active_milliseconds"],
                "console_log_count": row["console_log_count"],
                "console_warn_count": row["console_warn_count"],
                "console_error_count": row["console_error_count"],
                "size": row["size"],
                "event_count": row["event_count"],
                "message_count": row["message_count"],
                "snapshot_source": row["snapshot_source"],
                "retention_period_days": row["retention_period_days"],
                "block_first_timestamps": row["block_first_timestamps"],
                "block_last_timestamps": row["block_last_timestamps"],
                "block_urls": row["block_urls"],
            },
            workload=Workload.OFFLINE,
        )


def _insert_events(json_file: Path) -> None:
    with open(json_file) as f:
        rows = _parse_clickhouse_json(f.read())

    if not rows:
        return

    logger.info(
        "import_replay_events",
        file=json_file.name,
        row_count=len(rows),
    )

    sync_execute(
        """
        INSERT INTO writable_events (
            uuid,
            team_id,
            event,
            distinct_id,
            properties,
            timestamp,
            created_at,
            person_id,
            person_properties,
            elements_chain,
        ) VALUES
        """,
        [
            (
                row.get("uuid"),
                row.get("team_id"),
                row.get("event"),
                row.get("distinct_id"),
                row.get("properties", "{}"),
                _parse_timestamp(row.get("timestamp")),
                _parse_timestamp(row.get("created_at") or row.get("timestamp")),
                row.get("person_id"),
                row.get("person_properties", "{}"),
                row.get("elements_chain", ""),
            )
            for row in rows
        ],
        workload=Workload.OFFLINE,
    )
