import io
import os
from datetime import date, datetime, timedelta

import pytest
from unittest.mock import patch

import pyarrow.parquet as pq

from posthog.temporal.session_replay.surfacing_score_export_sweep.activities import (
    _PARQUET_SCHEMA,
    _page_table,
    export_days,
    exportable_rows,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    EXPORT_FLOOR_DAY,
    RAW_SESSION_IDENTIFIERS_START,
    REEXPORT_WINDOW_DAYS,
    SCORE_EXPORT_PREFIX_ENV_VAR,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.s3 import score_export_object_key

SESSION_ID = "0199a1cf-13d0-7c07-a301-d2e19a7c2a55"
AFTER_CUTOFF = RAW_SESSION_IDENTIFIERS_START + timedelta(hours=1)


class TestExportDays:
    def test_never_includes_days_before_the_floor(self) -> None:
        days = export_days(EXPORT_FLOOR_DAY + timedelta(days=2))
        assert days == [EXPORT_FLOOR_DAY.isoformat(), (EXPORT_FLOOR_DAY + timedelta(days=1)).isoformat()]

    def test_excludes_the_current_incomplete_day(self) -> None:
        today = date(2027, 1, 15)
        days = export_days(today)
        assert today.isoformat() not in days
        assert max(days) == "2027-01-14"
        assert len(days) == REEXPORT_WINDOW_DAYS

    def test_empty_before_any_complete_day_past_the_floor(self) -> None:
        assert export_days(EXPORT_FLOOR_DAY) == []


class TestExportableRows:
    def test_drops_non_opted_in_teams_and_pre_cutoff_sessions(self) -> None:
        rows = [
            (42, "kept", AFTER_CUTOFF, 0.9),
            (43, "no-consent", AFTER_CUTOFF, 0.9),
            (42, "pseudonym-era", RAW_SESSION_IDENTIFIERS_START - timedelta(seconds=1), 0.9),
            # ClickHouse hands back naive datetimes; they are UTC.
            (42, "naive-at-cutoff", RAW_SESSION_IDENTIFIERS_START.replace(tzinfo=None), 0.9),
        ]
        kept, dropped = exportable_rows(rows, frozenset({42}))
        assert [row[1] for row in kept] == ["kept", "naive-at-cutoff"]
        assert dropped == 2

    def test_nothing_survives_without_opted_in_teams(self) -> None:
        assert exportable_rows([(42, SESSION_ID, AFTER_CUTOFF, 0.5)], frozenset()) == ([], 1)


def _write_pages(pages: list[list[tuple[int, str, datetime, float]]]) -> bytes:
    sink = io.BytesIO()
    writer = pq.ParquetWriter(sink, _PARQUET_SCHEMA, compression="snappy")
    for page in pages:
        writer.write_table(_page_table(page))
    writer.close()
    return sink.getvalue()


class TestPartitionParquet:
    def test_writes_real_ids_and_round_trips_across_pages(self) -> None:
        body = _write_pages([[(42, SESSION_ID, AFTER_CUTOFF, 0.75)], [(43, "another-session", AFTER_CUTOFF, 0.25)]])

        table = pq.read_table(io.BytesIO(body))
        assert table.num_rows == 2
        row = table.to_pylist()[0]
        assert row["session_id"] == SESSION_ID
        assert row["team_id"] == "42"
        assert row["started_at"] == AFTER_CUTOFF
        assert row["surfacing_score"] == pytest.approx(0.75)

    def test_no_pages_still_writes_a_readable_object_with_the_schema(self) -> None:
        table = pq.read_table(io.BytesIO(_write_pages([])))
        assert table.num_rows == 0
        assert table.schema.names == ["session_id", "team_id", "started_at", "surfacing_score"]


class TestObjectKey:
    def test_defaults_under_the_score_prefix_the_bucket_policy_grants(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(SCORE_EXPORT_PREFIX_ENV_VAR, None)
            assert score_export_object_key("2026-09-16", 3, 8) == "score/v2/dt=2026-09-16/part-0003-of-0008.parquet"

    def test_prefix_override_is_honored(self) -> None:
        with patch.dict(os.environ, {SCORE_EXPORT_PREFIX_ENV_VAR: "score/staging"}):
            assert score_export_object_key("2026-09-16", 0, 1).startswith("score/staging/dt=2026-09-16/")
