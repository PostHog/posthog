import io
import os
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import pytest
from unittest.mock import MagicMock, patch

import pyarrow.parquet as pq

from posthog.temporal.session_replay.surfacing_score_export_sweep import activities
from posthog.temporal.session_replay.surfacing_score_export_sweep.activities import (
    _PARQUET_SCHEMA,
    OPTED_IN_TEAMS_TTL_S,
    _opted_in_team_ids,
    _page_table,
    export_days,
    exportable_rows,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    BACKFILL_UNTIL,
    EXPORT_FLOOR_DAY,
    REEXPORT_WINDOW_DAYS,
    SCORE_EXPORT_PREFIX_ENV_VAR,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.s3 import score_export_object_key
from posthog.temporal.session_replay.surfacing_score_export_sweep.session_identifier_format import (
    RAW_SESSION_IDENTIFIERS_START,
)
from posthog.uuidt import uuid7

AFTER_CUTOFF = RAW_SESSION_IDENTIFIERS_START + timedelta(hours=1)
SESSION_ID = str(uuid7(int(AFTER_CUTOFF.timestamp() * 1000)))
OTHER_SESSION_ID = str(uuid7(int(AFTER_CUTOFF.timestamp() * 1000) + 1))
PSEUDONYM_ERA_SESSION_ID = str(uuid7(int(RAW_SESSION_IDENTIFIERS_START.timestamp() * 1000) - 1000))
FIRST_DEPLOY_DAY = date(2026, 9, 24)


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

    def test_exports_the_cutoff_day_on_the_first_deployment_day(self) -> None:
        days = export_days(FIRST_DEPLOY_DAY)
        assert days[0] == EXPORT_FLOOR_DAY.isoformat() == "2026-09-15"
        assert days[-1] == "2026-09-23"

    def test_backfill_expires_back_to_the_trailing_window(self) -> None:
        days = export_days(date(2026, 10, 2))
        assert len(days) == REEXPORT_WINDOW_DAYS
        assert days[0] == "2026-09-24"

    def test_first_deployment_day_is_inside_the_backfill_window(self) -> None:
        assert FIRST_DEPLOY_DAY < BACKFILL_UNTIL


class TestExportableRows:
    def test_drops_non_opted_in_teams_and_ids_the_mirror_pseudonymized(self) -> None:
        rows = [
            (42, SESSION_ID, AFTER_CUTOFF, 0.9),
            (43, OTHER_SESSION_ID, AFTER_CUTOFF, 0.9),
            (42, PSEUDONYM_ERA_SESSION_ID, AFTER_CUTOFF, 0.9),
            (42, "legacy-session", AFTER_CUTOFF, 0.9),
        ]
        kept, dropped = exportable_rows(rows, frozenset({42}))
        assert [row[1] for row in kept] == [SESSION_ID]
        assert dropped == 3

    def test_eligibility_follows_the_session_id_not_the_aggregated_start(self) -> None:
        rows = [
            (42, SESSION_ID, RAW_SESSION_IDENTIFIERS_START - timedelta(hours=2), 0.9),
            (42, PSEUDONYM_ERA_SESSION_ID, AFTER_CUTOFF, 0.9),
        ]
        kept, dropped = exportable_rows(rows, frozenset({42}))
        assert [row[1] for row in kept] == [SESSION_ID]
        assert dropped == 1

    def test_nothing_survives_without_opted_in_teams(self) -> None:
        assert exportable_rows([(42, SESSION_ID, AFTER_CUTOFF, 0.5)], frozenset()) == ([], 1)


class TestOptedInTeamIdsCache:
    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> Iterator[None]:
        activities._opted_in_teams_cache = None
        yield
        activities._opted_in_teams_cache = None

    @staticmethod
    def _team_manager(team_ids: list[int]) -> MagicMock:
        manager = MagicMock()
        manager.objects.filter.return_value.values_list.return_value = team_ids
        return manager

    def test_one_scan_serves_every_partition_of_a_sweep(self) -> None:
        team = self._team_manager([42, 43])
        with patch.object(activities, "Team", team):
            assert [_opted_in_team_ids() for _ in range(8)] == [frozenset({42, 43})] * 8
        assert team.objects.filter.call_count == 1

    def test_rescans_once_the_mirrors_refresh_interval_has_passed(self) -> None:
        team = self._team_manager([42])
        clock = [0.0]
        with patch.object(activities, "Team", team), patch.object(activities.time, "monotonic", lambda: clock[0]):
            _opted_in_team_ids()
            clock[0] = OPTED_IN_TEAMS_TTL_S - 1
            _opted_in_team_ids()
            assert team.objects.filter.call_count == 1

            clock[0] = OPTED_IN_TEAMS_TTL_S + 1
            _opted_in_team_ids()
        assert team.objects.filter.call_count == 2


def _write_pages(pages: list[list[tuple[int, str, datetime, float]]]) -> bytes:
    sink = io.BytesIO()
    writer = pq.ParquetWriter(sink, _PARQUET_SCHEMA, compression="snappy")
    for page in pages:
        writer.write_table(_page_table(page))
    writer.close()
    return sink.getvalue()


class TestPartitionParquet:
    def test_writes_real_ids_and_round_trips_across_pages(self) -> None:
        body = _write_pages([[(42, SESSION_ID, AFTER_CUTOFF, 0.75)], [(43, OTHER_SESSION_ID, AFTER_CUTOFF, 0.25)]])

        table = pq.read_table(io.BytesIO(body))
        assert table.num_rows == 2
        row = table.to_pylist()[0]
        assert row["session_id"] == SESSION_ID
        assert row["team_id"] == "42"
        assert row["started_at"] == AFTER_CUTOFF
        assert row["surfacing_score"] == pytest.approx(0.75)

    def test_reads_a_naive_clickhouse_start_as_utc(self) -> None:
        body = _write_pages([[(42, SESSION_ID, AFTER_CUTOFF.replace(tzinfo=None), 0.5)]])
        assert pq.read_table(io.BytesIO(body)).to_pylist()[0]["started_at"] == AFTER_CUTOFF

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
