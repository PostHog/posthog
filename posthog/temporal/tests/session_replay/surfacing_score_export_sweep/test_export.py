import io
import os
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

import pyarrow.parquet as pq
from temporalio.testing import ActivityEnvironment

from posthog.ai_training_privacy_reader import TrainingDataKey, TrainingKeyIdentity, TrainingKeyLocation
from posthog.temporal.session_replay.surfacing_score_export_sweep.activities import (
    _PARQUET_SCHEMA,
    _page_table,
    export_days,
    export_encrypted_scores_page_activity,
    export_scores_partition_activity,
    list_export_partitions_activity,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    EXPORT_FLOOR_DAY,
    REEXPORT_WINDOW_DAYS,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.pseudonymize import resolve_pseudonym_key
from posthog.temporal.session_replay.surfacing_score_export_sweep.s3 import (
    score_export_destination,
    score_export_object_key,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.types import (
    EncryptedScorePage,
    ExportPartitionSpec,
    ExportScoresSweepInputs,
)


class TestExportDays:
    def test_never_includes_days_before_the_floor(self) -> None:
        days = export_days(date(2026, 7, 6))
        assert days == [EXPORT_FLOOR_DAY.isoformat(), "2026-07-05"]

    def test_excludes_the_current_incomplete_day(self) -> None:
        today = date(2027, 1, 15)
        days = export_days(today)
        assert today.isoformat() not in days
        assert max(days) == "2027-01-14"
        assert len(days) == REEXPORT_WINDOW_DAYS

    def test_empty_before_any_complete_day_past_the_floor(self) -> None:
        assert export_days(EXPORT_FLOOR_DAY) == []


def _write_pages(pages: list[list[tuple[int, str, datetime, float]]]) -> bytes:
    sink = io.BytesIO()
    writer = pq.ParquetWriter(sink, _PARQUET_SCHEMA, compression="snappy")
    for page in pages:
        writer.write_table(_page_table(page))
    writer.close()
    return sink.getvalue()


class TestPartitionParquet:
    def test_preserves_team_and_session_ids_across_pages(self) -> None:
        started_at = datetime(2026, 7, 4, 12, 30, tzinfo=UTC)
        session_id = "0197d1cf-13d0-7c07-a301-d2e19a7c2a55"
        body = _write_pages([[(42, session_id, started_at, 0.75)], [(43, "another-session", started_at, 0.25)]])

        table = pq.read_table(io.BytesIO(body))
        assert table.num_rows == 2
        row = table.to_pylist()[0]
        assert row["session_id"] == session_id
        assert row["team_id"] == "42"
        assert table.to_pylist()[1]["team_id"] == "43"
        assert row["started_at"] == started_at
        assert row["surfacing_score"] == pytest.approx(0.75)
        assert table.to_pylist()[1]["session_id"] == "another-session"

    def test_no_pages_still_writes_a_readable_object_with_the_schema(self) -> None:
        table = pq.read_table(io.BytesIO(_write_pages([])))
        assert table.num_rows == 0
        assert table.schema.names == ["session_id", "team_id", "started_at", "surfacing_score"]


_FORMAT_CASES = json.loads(
    (
        Path(__file__).resolve().parents[5]
        / "nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format-cases.json"
    ).read_text()
)["cases"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mixed", "raw_only", "legacy_only", "empty"])
@pytest.mark.parametrize("env_prefix", ["AI_RESEARCH_REPLAY_", "SESSION_RECORDING_ML_"])
async def test_exports_sessions_to_the_same_format_as_the_mirror(mode: str, env_prefix: str) -> None:
    cases = [
        case
        for case in _FORMAT_CASES
        if mode == "mixed"
        or (mode == "raw_only" and case["rawIdentifiers"])
        or (mode == "legacy_only" and not case["rawIdentifiers"])
    ]
    started_at = datetime(2026, 9, 12, 12, 30, tzinfo=UTC)
    rows = [(7, case["sessionId"], started_at, 0.75) for case in cases]
    pages = [rows[i : i + 2] for i in range(0, len(rows), 2)]
    if not rows or len(rows) % 2 == 0:
        pages.append([])
    environment = {f"{env_prefix}SCORE_EXPORT_S3_BUCKET": "ml-bucket"}
    if any(not case["rawIdentifiers"] for case in cases):
        environment[f"{env_prefix}PSEUDONYM_SECRET"] = "test-secret"
    keys = {
        TrainingKeyLocation.session(7, row[1]): TrainingDataKey(
            identity=TrainingKeyIdentity(
                team_id=7, organization_id="test-org", session_id=row[1], consent_granted_at=1
            ),
            plaintext=bytes([7]) * 32,
        )
        for row in rows
    }
    reader = MagicMock()
    reader.read.side_effect = lambda locations: {location: keys[location] for location in locations if location in keys}
    activity_environment = ActivityEnvironment()
    with (
        patch.dict(os.environ, environment, clear=True),
        patch(
            "posthog.temporal.session_replay.surfacing_score_export_sweep.activities._score_key_reader",
            return_value=reader,
        ),
        patch("posthog.temporal.session_replay.surfacing_score_export_sweep.pseudonymize._SECRET", None),
        patch("posthog.temporal.session_replay.surfacing_score_export_sweep.activities.EXPORT_PAGE_MAX_ROWS", 2),
        patch(
            "posthog.temporal.session_replay.surfacing_score_export_sweep.activities.sync_execute", side_effect=pages
        ),
        patch("posthog.temporal.session_replay.surfacing_score_export_sweep.activities.boto3_client") as client,
    ):
        partitions = await activity_environment.run(list_export_partitions_activity, ExportScoresSweepInputs())
        assert partitions.disabled_reason is None
        result = await activity_environment.run(
            export_scores_partition_activity,
            ExportPartitionSpec(day="2026-09-12", chunk_id=0, of_chunks=1),
        )

    assert result.rows == len(rows)
    assert all(call.args == ("s3",) for call in client.call_args_list)
    uploads = client.return_value.put_object.call_args_list
    assert len(uploads) == 2
    for raw_identifiers, prefix in [(False, "score"), (True, "score/v2")]:
        upload = next(
            call.kwargs for call in uploads if call.kwargs["Key"] == f"{prefix}/dt=2026-09-12/part-0000-of-0001.parquet"
        )
        assert upload["Bucket"] == "ml-bucket"
        actual = pq.read_table(io.BytesIO(upload["Body"])).to_pylist()
        if raw_identifiers:
            assert all("surfacing_score" not in row for row in actual)
            actual = [
                {
                    "team_id": row["team_id"],
                    "session_id": row["session_id"],
                    **json.loads(
                        keys[TrainingKeyLocation.session(7, row["session_id"])].decrypt(row["payload"], "score")
                    ),
                }
                for row in actual
            ]
            for row in actual:
                row["started_at"] = datetime.fromisoformat(row["started_at"])
        assert actual == [
            {
                "team_id": case["storedTeamId"],
                "session_id": case["storedSessionId"],
                "started_at": started_at,
                "surfacing_score": 0.75,
            }
            for case in cases
            if case["rawIdentifiers"] == raw_identifiers
        ]


@pytest.mark.parametrize("prefix", ["AI_RESEARCH_REPLAY_", "SESSION_RECORDING_ML_"])
def test_score_destination_accepts_both_setting_names(prefix: str) -> None:
    with patch.dict(
        os.environ,
        {
            f"{prefix}SCORE_EXPORT_S3_BUCKET": "ml-bucket",
            f"{prefix}SCORE_EXPORT_S3_REGION": "us-west-2",
            f"{prefix}SCORE_EXPORT_S3_ENDPOINT": "https://storage.example.com",
            f"{prefix}SCORE_EXPORT_S3_ACCESS_KEY_ID": "test-access-key",
            f"{prefix}SCORE_EXPORT_S3_SECRET_ACCESS_KEY": "test-secret-key",
            f"{prefix}SCORE_EXPORT_PREFIX": "custom-scores",
        },
        clear=True,
    ):
        destination = score_export_destination()
        assert destination is not None
        assert destination.bucket == "ml-bucket"
        assert destination.region == "us-west-2"
        assert destination.endpoint == "https://storage.example.com"
        assert destination.access_key_id == "test-access-key"
        assert destination.secret_access_key == "test-secret-key"
        assert score_export_object_key("2026-09-12", 0, 1).startswith("custom-scores/v2/")


@pytest.mark.parametrize("bucket", ["canonical-bucket", ""])
def test_score_destination_prefers_canonical_settings_including_empty(bucket: str) -> None:
    with patch.dict(
        os.environ,
        {
            "AI_RESEARCH_REPLAY_SCORE_EXPORT_S3_BUCKET": bucket,
            "SESSION_RECORDING_ML_SCORE_EXPORT_S3_BUCKET": "legacy-bucket",
        },
        clear=True,
    ):
        destination = score_export_destination()
        if bucket:
            assert destination is not None
            assert destination.bucket == bucket
        else:
            assert destination is None


@pytest.mark.parametrize("prefix", ["AI_RESEARCH_REPLAY_", "SESSION_RECORDING_ML_"])
def test_legacy_key_uses_the_configured_wrapped_key_and_region(prefix: str) -> None:
    with (
        patch.dict(
            os.environ,
            {
                "SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY": "dGVzdA==",
                f"{prefix}PSEUDONYM_KMS_REGION": "us-west-2",
                f"{prefix}PSEUDONYM_KEY_FINGERPRINT": "db7dc188104c2bae",
            },
            clear=True,
        ),
        patch("posthog.temporal.session_replay.surfacing_score_export_sweep.pseudonymize._SECRET", None),
        patch("posthog.temporal.session_replay.surfacing_score_export_sweep.pseudonymize.boto3_client") as client,
    ):
        client.return_value.decrypt.return_value = {"Plaintext": b"super-secret"}
        assert resolve_pseudonym_key() == b"super-secret"
    client.assert_called_once_with("kms", region_name="us-west-2")
    client.return_value.decrypt.assert_called_once_with(CiphertextBlob=b"test")


@pytest.mark.asyncio
async def test_encrypted_export_publishes_manifest_only_after_last_page() -> None:
    session_id = next(case["sessionId"] for case in _FORMAT_CASES if case["rawIdentifiers"])
    rows = [(7, session_id, datetime(2026, 9, 14, 12, tzinfo=UTC), 0.75)]
    reader = MagicMock()
    reader.read.return_value = {}
    page = EncryptedScorePage(
        partition=ExportPartitionSpec(day="2026-09-14", chunk_id=0, of_chunks=1), export_id="test-export"
    )
    environment = ActivityEnvironment()
    with (
        patch("posthog.temporal.session_replay.surfacing_score_export_sweep.activities.ENCRYPTED_EXPORT_PAGE_ROWS", 1),
        patch(
            "posthog.temporal.session_replay.surfacing_score_export_sweep.activities._fetch_page",
            side_effect=[rows, []],
        ) as fetch,
        patch(
            "posthog.temporal.session_replay.surfacing_score_export_sweep.activities._score_key_reader",
            return_value=reader,
        ),
        patch("posthog.temporal.session_replay.surfacing_score_export_sweep.activities._upload") as upload,
        patch(
            "posthog.temporal.session_replay.surfacing_score_export_sweep.activities._publish_encrypted_score_manifest"
        ) as publish,
    ):
        first = await environment.run(export_encrypted_scores_page_activity, page)
        assert first.next_page is not None
        publish.assert_not_called()
        assert pq.read_table(io.BytesIO(upload.call_args.args[1])).num_rows == 0
        last = await environment.run(export_encrypted_scores_page_activity, first.next_page)
        assert last.next_page is None
        publish.assert_called_once_with(first.next_page)
        assert fetch.call_args.args[1] == (session_id, 7)
        assert upload.call_args_list[0].args[0] != upload.call_args_list[1].args[0]
