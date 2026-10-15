import io
from datetime import UTC, date, datetime

import pytest

from django.test import TestCase

import pyarrow.parquet as pq

from posthog.models import Organization, Team
from posthog.temporal.session_replay.surfacing_score_export_sweep.activities import (
    _PARQUET_SCHEMA,
    _page_table,
    ai_training_opted_in_team_ids,
    export_days,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    EXPORT_FLOOR_DAY,
    REEXPORT_WINDOW_DAYS,
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


def _write_pages(pages: list[list[tuple[int, str, datetime, float]]], opted_in: frozenset[int]) -> bytes:
    sink = io.BytesIO()
    writer = pq.ParquetWriter(sink, _PARQUET_SCHEMA, compression="snappy")
    for page in pages:
        writer.write_table(_page_table(page, opted_in))
    writer.close()
    return sink.getvalue()


class TestPartitionParquet:
    def test_exports_raw_ids_of_opted_in_teams_only_across_pages(self) -> None:
        started_at = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
        session_id = "019a1f2e-13d0-7c07-a301-d2e19a7c2a55"
        opted_out_session_id = "019a1f2e-13d0-7c07-a301-d2e19a7c2a56"
        body = _write_pages(
            [[(42, session_id, started_at, 0.75)], [(43, opted_out_session_id, started_at, 0.25)]],
            frozenset({42}),
        )

        table = pq.read_table(io.BytesIO(body))
        assert table.to_pylist() == [
            {
                "session_id": session_id,
                "team_id": "42",
                "started_at": started_at,
                "surfacing_score": pytest.approx(0.75),
            }
        ]
        assert opted_out_session_id not in body.decode("latin-1")

    def test_no_pages_still_writes_a_readable_object_with_the_schema(self) -> None:
        table = pq.read_table(io.BytesIO(_write_pages([], frozenset())))
        assert table.num_rows == 0
        assert table.schema.names == ["session_id", "team_id", "started_at", "surfacing_score"]


class TestOptedInTeams(TestCase):
    def test_only_an_explicit_opt_in_counts(self) -> None:
        teams = {}
        for consent in (True, False, None):
            organization = Organization.objects.create(name=f"org {consent}", is_ai_training_opted_in=consent)
            teams[consent] = Team.objects.create(organization=organization, name=f"team {consent}")

        assert ai_training_opted_in_team_ids() == frozenset({teams[True].id})
