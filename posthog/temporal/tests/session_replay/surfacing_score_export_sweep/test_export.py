import io
import os
from datetime import UTC, date, datetime

import pytest
from unittest.mock import patch

import pyarrow.parquet as pq
from temporalio.testing import ActivityEnvironment

from posthog.temporal.session_replay.surfacing_score_export_sweep.activities import (
    _PARQUET_SCHEMA,
    _page_table,
    export_days,
    export_scores_partition_activity,
    list_export_partitions_activity,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    EXPORT_FLOOR_DAY,
    REEXPORT_WINDOW_DAYS,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.types import (
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


@pytest.mark.asyncio
async def test_exports_raw_ids_without_a_pseudonym_key() -> None:
    started_at = datetime(2026, 7, 4, 12, 30, tzinfo=UTC)
    activity_environment = ActivityEnvironment()
    with (
        patch.dict(os.environ, {"SESSION_RECORDING_ML_SCORE_EXPORT_S3_BUCKET": "ml-bucket"}, clear=True),
        patch(
            "posthog.temporal.session_replay.surfacing_score_export_sweep.activities.sync_execute",
            return_value=[(42, "session-1", started_at, 0.75)],
        ),
        patch("posthog.temporal.session_replay.surfacing_score_export_sweep.activities.boto3_client") as client,
    ):
        partitions = await activity_environment.run(list_export_partitions_activity, ExportScoresSweepInputs())
        assert partitions.disabled_reason is None
        result = await activity_environment.run(
            export_scores_partition_activity, ExportPartitionSpec(day="2026-07-04", chunk_id=0, of_chunks=1)
        )

    assert result.rows == 1
    assert client.call_count == 1
    assert client.call_args.args == ("s3",)
    upload = client.return_value.put_object.call_args.kwargs
    assert upload["Bucket"] == "ml-bucket"
    assert upload["Key"] == "score/v2/dt=2026-07-04/part-0000-of-0001.parquet"
    assert pq.read_table(io.BytesIO(upload["Body"])).to_pylist() == [
        {"team_id": "42", "session_id": "session-1", "started_at": started_at, "surfacing_score": 0.75}
    ]
