import os
import json
import zipfile
import tempfile
from pathlib import Path

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)


def process_replay_import(team_id: int, zip_file_path: str, triggered_by: str) -> None:
    logger.info(
        "import_replay_data_started",
        team_id=team_id,
        zip_file_path=zip_file_path,
        triggered_by=triggered_by,
    )

    try:
        with tempfile.TemporaryDirectory() as extract_dir:
            with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)

            extract_path = Path(extract_dir)

            metadata_path = extract_path / "metadata.json"
            if metadata_path.exists():
                with open(metadata_path) as f:
                    metadata = json.load(f)
                logger.info("import_replay_metadata", team_id=team_id, metadata=metadata)

            _copy_s3_files(team_id, extract_path)
            _insert_clickhouse_data(team_id, extract_path)

        logger.info(
            "import_replay_data_completed",
            team_id=team_id,
            zip_file_path=zip_file_path,
        )
    finally:
        if os.path.exists(zip_file_path):
            os.unlink(zip_file_path)


def _copy_s3_files(team_id: int, extract_path: Path) -> None:
    for root, _dirs, files in os.walk(extract_path):
        root_path = Path(root)
        relative_root = root_path.relative_to(extract_path)

        if str(relative_root).startswith("clickhouse"):
            continue

        if str(relative_root) == "." and any(f == "metadata.json" for f in files):
            continue

        for file_name in files:
            if file_name == "metadata.json":
                continue

            file_path = root_path / file_name
            s3_key = str(relative_root / file_name) if str(relative_root) != "." else file_name

            with open(file_path, "rb") as f:
                content = f.read()

            logger.info(
                "import_replay_s3_file",
                team_id=team_id,
                s3_key=s3_key,
                size=len(content),
            )

            object_storage.write(s3_key, content)


def _insert_clickhouse_data(team_id: int, extract_path: Path) -> None:
    clickhouse_dir = extract_path / "clickhouse"
    if not clickhouse_dir.exists():
        logger.info("import_replay_no_clickhouse_data", team_id=team_id)
        return

    session_replay_events_dir = clickhouse_dir / "session-replay-events"
    if session_replay_events_dir.exists():
        _insert_session_replay_events(team_id, session_replay_events_dir)

    events_dir = clickhouse_dir / "events"
    if events_dir.exists():
        _insert_events(team_id, events_dir)


def _insert_session_replay_events(team_id: int, data_dir: Path) -> None:
    for json_file in data_dir.glob("*.json"):
        with open(json_file) as f:
            rows = json.load(f)

        if not rows:
            continue

        logger.info(
            "import_replay_session_replay_events",
            team_id=team_id,
            file=json_file.name,
            row_count=len(rows),
        )

        for row in rows:
            row["team_id"] = team_id

        sync_execute(
            """
            INSERT INTO session_replay_events (
                session_id,
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
                snapshot_source
            ) VALUES
            """,
            [
                (
                    row.get("session_id"),
                    row.get("team_id"),
                    row.get("distinct_id"),
                    row.get("min_first_timestamp"),
                    row.get("max_last_timestamp"),
                    row.get("first_url"),
                    row.get("click_count", 0),
                    row.get("keypress_count", 0),
                    row.get("mouse_activity_count", 0),
                    row.get("active_milliseconds", 0),
                    row.get("console_log_count", 0),
                    row.get("console_warn_count", 0),
                    row.get("console_error_count", 0),
                    row.get("size", 0),
                    row.get("event_count", 0),
                    row.get("message_count", 0),
                    row.get("snapshot_source"),
                )
                for row in rows
            ],
            workload=Workload.OFFLINE,
            team_id=team_id,
        )


def _insert_events(team_id: int, data_dir: Path) -> None:
    for json_file in data_dir.glob("*.json"):
        with open(json_file) as f:
            rows = json.load(f)

        if not rows:
            continue

        logger.info(
            "import_replay_events",
            team_id=team_id,
            file=json_file.name,
            row_count=len(rows),
        )

        for row in rows:
            row["team_id"] = team_id

        sync_execute(
            """
            INSERT INTO events (
                uuid,
                team_id,
                event,
                distinct_id,
                properties,
                timestamp,
                created_at,
                person_id,
                person_properties,
                elements_chain
            ) VALUES
            """,
            [
                (
                    row.get("uuid"),
                    row.get("team_id"),
                    row.get("event"),
                    row.get("distinct_id"),
                    json.dumps(row.get("properties", {})),
                    row.get("timestamp"),
                    row.get("created_at"),
                    row.get("person_id"),
                    json.dumps(row.get("person_properties", {})),
                    row.get("elements_chain", ""),
                )
                for row in rows
            ],
            workload=Workload.OFFLINE,
            team_id=team_id,
        )
