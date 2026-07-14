# Golden vectors generated from the Node source of truth (nodejs/.../ml-mirror/pseudonymize.ts).

import io
from datetime import UTC, date, datetime

import pytest

import pyarrow.parquet as pq
from parameterized import parameterized

from posthog.temporal.session_replay.surfacing_score_export_sweep import sql as export_sql
from posthog.temporal.session_replay.surfacing_score_export_sweep.activities import (
    _PARQUET_SCHEMA,
    _opted_in_teams_external_table,
    _page_table,
    export_days,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    EXPORT_FLOOR_DAY,
    REEXPORT_WINDOW_DAYS,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.pseudonymize import (
    PSEUDONYM_SESSION,
    PSEUDONYM_TEAM,
    pseudonym_key_fingerprint,
    pseudonymize,
)

SECRET = b"super-secret"


class TestPseudonymizeNodeParity:
    @parameterized.expand(
        [
            (PSEUDONYM_SESSION, "0197d1cf-13d0-7c07-a301-d2e19a7c2a55", "5f004a2baeeb5c761c6ba2c70730961c"),
            (PSEUDONYM_TEAM, "42", "a424b2c7c7d5b495e6479d058e5f751c"),
        ]
    )
    def test_matches_node_golden_vector(self, namespace: str, value: str, expected: str) -> None:
        assert pseudonymize(SECRET, namespace, value) == expected

    def test_fingerprint_matches_node_golden_vector(self) -> None:
        assert pseudonym_key_fingerprint(SECRET) == "db7dc188104c2bae"


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
        writer.write_table(_page_table(page, SECRET))
    writer.close()
    return sink.getvalue()


class TestPartitionParquet:
    def test_pseudonymizes_ids_and_round_trips_across_pages(self) -> None:
        started_at = datetime(2026, 7, 4, 12, 30, tzinfo=UTC)
        session_id = "0197d1cf-13d0-7c07-a301-d2e19a7c2a55"
        body = _write_pages([[(42, session_id, started_at, 0.75)], [(43, "another-session", started_at, 0.25)]])

        table = pq.read_table(io.BytesIO(body))
        assert table.num_rows == 2
        row = table.to_pylist()[0]
        assert row["session_id"] == "5f004a2baeeb5c761c6ba2c70730961c"
        assert row["team_id"] == "a424b2c7c7d5b495e6479d058e5f751c"
        assert row["started_at"] == started_at
        assert row["surfacing_score"] == pytest.approx(0.75)
        assert session_id not in body.decode("latin-1")

    def test_no_pages_still_writes_a_readable_object_with_the_schema(self) -> None:
        table = pq.read_table(io.BytesIO(_write_pages([])))
        assert table.num_rows == 0
        assert table.schema.names == ["session_id", "team_id", "started_at", "surfacing_score"]


class TestOptedInTeamFilter:
    def test_page_sql_never_inlines_the_team_id_list(self) -> None:
        sql = export_sql.fetch_scored_sessions_page_sql()
        assert "%(team_ids)s" not in sql
        assert sql.count(f"team_id GLOBAL IN (SELECT team_id FROM {export_sql.OPTED_IN_TEAMS_EXTERNAL_TABLE})") == 2

    def test_external_table_carries_team_ids_out_of_band(self) -> None:
        table = _opted_in_teams_external_table([7, 42])
        assert table["name"] == export_sql.OPTED_IN_TEAMS_EXTERNAL_TABLE
        assert table["structure"] == [("team_id", "Int64")]
        assert table["data"] == [{"team_id": 7}, {"team_id": 42}]
