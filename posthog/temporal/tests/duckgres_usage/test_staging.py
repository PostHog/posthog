"""Tests for the duckgres usage staging table and its replace-window semantics.

The staging table holds day-keyed usage pulled from duckgres. Because we only
ack at UTC day boundaries, every pull returns complete day-so-far totals for
the open window, so applying a response is a pure replace: delete the window's
dates, insert the response's rows, in one transaction. Idempotent and
self-healing — a bad write is overwritten by the next pull.

Watermark subtlety encoded here: duckgres watermarks are bucket-START labels
and ack deletes `bucket_start <= watermark`, so our acks are
`start_of_open_day - 1s` (23:59:59 of the last complete day). The replace
window's first date must therefore be `(watermark_low + 1s).date()` — using
`watermark_low.date()` would delete the already-acked previous day, whose data
duckgres will never re-serve.
"""

import datetime as dt
from decimal import Decimal

import pytest

from posthog.ducklake.models import DuckgresDailyStorageUsage, DuckgresDailyUsage
from posthog.temporal.duckgres_usage.client import StorageRow, UsageResponse, UsageRow
from posthog.temporal.duckgres_usage.staging import replace_window

pytestmark = pytest.mark.django_db

ORG = "018f0000-0000-0000-0000-000000000000"


def _row(
    date: dt.date,
    team_id: int = 42,
    query_source: str = "standard",
    cpu: str = "8",
    mem_gib: str = "16",
    cpu_seconds: int = 100,
    memory_seconds: int = 800,
) -> UsageRow:
    return UsageRow(
        date=date,
        org_id=ORG,
        team_id=team_id,
        query_source=query_source,
        cpu=Decimal(cpu),
        mem_gib=Decimal(mem_gib),
        cpu_seconds=cpu_seconds,
        memory_seconds=memory_seconds,
    )


def _seed(date: dt.date, team_id: int = 42, query_source: str = "standard", cpu_seconds: int = 1) -> DuckgresDailyUsage:
    return DuckgresDailyUsage.objects.create(
        date=date,
        organization_id=ORG,
        team_id=team_id,
        query_source=query_source,
        cpu=Decimal("8"),
        mem_gib=Decimal("16"),
        cpu_seconds=cpu_seconds,
        memory_seconds=8,
    )


def _response(
    rows: list[UsageRow],
    low: dt.datetime,
    high: dt.datetime,
    storage_rows: list[StorageRow] | None = None,
) -> UsageResponse:
    return UsageResponse(watermark_low=low, watermark_high=high, rows=rows, storage_rows=storage_rows or [])


def _storage_row(date: dt.date, team_id: int = 42, gib_seconds: str = "360000") -> StorageRow:
    return StorageRow(date=date, org_id=ORG, team_id=team_id, gib_seconds=Decimal(gib_seconds))


class TestReplaceWindow:
    def test_inserts_rows_with_all_fields(self) -> None:
        response = _response(
            [_row(dt.date(2026, 7, 7), cpu="1.5", mem_gib="0.5", cpu_seconds=90, memory_seconds=30)],
            low=dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC),
            high=dt.datetime(2026, 7, 7, 12, 39, tzinfo=dt.UTC),
        )

        replace_window(response)

        stored = DuckgresDailyUsage.objects.get()
        assert stored.date == dt.date(2026, 7, 7)
        assert str(stored.organization_id) == ORG
        assert stored.team_id == 42
        assert stored.query_source == "standard"
        assert stored.cpu == Decimal("1.5")
        assert stored.mem_gib == Decimal("0.5")
        assert stored.cpu_seconds == 90
        assert stored.memory_seconds == 30

    def test_overwrites_open_day_on_repull(self) -> None:
        low = dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC)
        replace_window(
            _response([_row(dt.date(2026, 7, 7), cpu_seconds=100)], low, dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.UTC))
        )

        replace_window(
            _response([_row(dt.date(2026, 7, 7), cpu_seconds=250)], low, dt.datetime(2026, 7, 7, 12, 10, tzinfo=dt.UTC))
        )

        stored = DuckgresDailyUsage.objects.get()
        assert stored.cpu_seconds == 250  # replaced, not 350

    def test_is_idempotent_for_the_same_response(self) -> None:
        response = _response(
            [_row(dt.date(2026, 7, 7)), _row(dt.date(2026, 7, 7), query_source="endpoints")],
            low=dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC),
            high=dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.UTC),
        )

        replace_window(response)
        replace_window(response)

        assert DuckgresDailyUsage.objects.count() == 2

    def test_preserves_days_before_the_window(self) -> None:
        # Day 6 was acked (low = 23:59:59 of day 6): duckgres will never
        # re-serve it, so replace must NOT touch it even though
        # watermark_low.date() == day 6.
        _seed(dt.date(2026, 7, 6), cpu_seconds=12345)
        response = _response(
            [_row(dt.date(2026, 7, 7))],
            low=dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC),
            high=dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.UTC),
        )

        replace_window(response)

        assert DuckgresDailyUsage.objects.get(date=dt.date(2026, 7, 6)).cpu_seconds == 12345
        assert DuckgresDailyUsage.objects.filter(date=dt.date(2026, 7, 7)).count() == 1

    def test_removes_stale_rows_for_window_days_absent_from_response(self) -> None:
        # A key that appeared in an earlier pull but is gone from this one
        # (e.g. duckgres corrected data) must not survive the replace.
        _seed(dt.date(2026, 7, 7), team_id=99)
        response = _response(
            [_row(dt.date(2026, 7, 7), team_id=42)],
            low=dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC),
            high=dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.UTC),
        )

        replace_window(response)

        assert not DuckgresDailyUsage.objects.filter(team_id=99).exists()

    def test_multi_day_window_replaces_every_day(self) -> None:
        # Catch-up after downtime: window spans a closed day + the open day.
        _seed(dt.date(2026, 7, 6), cpu_seconds=1)
        _seed(dt.date(2026, 7, 7), cpu_seconds=1)
        response = _response(
            [_row(dt.date(2026, 7, 6), cpu_seconds=600), _row(dt.date(2026, 7, 7), cpu_seconds=300)],
            low=dt.datetime(2026, 7, 5, 23, 59, 59, tzinfo=dt.UTC),
            high=dt.datetime(2026, 7, 7, 9, 0, tzinfo=dt.UTC),
        )

        replace_window(response)

        assert DuckgresDailyUsage.objects.get(date=dt.date(2026, 7, 6)).cpu_seconds == 600
        assert DuckgresDailyUsage.objects.get(date=dt.date(2026, 7, 7)).cpu_seconds == 300

    def test_replaces_row_dates_outside_derived_window(self) -> None:
        # Defensive: if duckgres's cursor regressed and re-serves an older day,
        # rows for that day must replace ours (not crash on the unique key).
        _seed(dt.date(2026, 7, 3), cpu_seconds=1)
        response = _response(
            [_row(dt.date(2026, 7, 3), cpu_seconds=500), _row(dt.date(2026, 7, 7))],
            low=dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC),
            high=dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.UTC),
        )

        replace_window(response)

        assert DuckgresDailyUsage.objects.get(date=dt.date(2026, 7, 3)).cpu_seconds == 500

    def test_first_pull_with_epoch_low_inserts_everything(self) -> None:
        # Never-acked cursor serves everything buffered; zero-time low must not
        # break the window derivation.
        response = _response(
            [_row(dt.date(2026, 7, 6)), _row(dt.date(2026, 7, 7))],
            low=dt.datetime(1, 1, 1, tzinfo=dt.UTC),
            high=dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.UTC),
        )

        replace_window(response)

        assert DuckgresDailyUsage.objects.count() == 2

    def test_empty_window_is_a_noop(self) -> None:
        _seed(dt.date(2026, 7, 7), cpu_seconds=42)
        low = high = dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC)

        replace_window(_response([], low, high))

        assert DuckgresDailyUsage.objects.get(date=dt.date(2026, 7, 7)).cpu_seconds == 42

    def test_worker_sizes_are_separate_rows(self) -> None:
        # Same (date, team, source) with different worker configs must coexist
        # (the unique key includes cpu + mem_gib).
        response = _response(
            [
                _row(dt.date(2026, 7, 7), cpu="8", mem_gib="16", cpu_seconds=100),
                _row(dt.date(2026, 7, 7), cpu="1.5", mem_gib="0.5", cpu_seconds=50),
            ],
            low=dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC),
            high=dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.UTC),
        )

        replace_window(response)

        assert DuckgresDailyUsage.objects.count() == 2


class TestReplaceWindowStorage:
    LOW = dt.datetime(2026, 7, 6, 23, 59, 59, tzinfo=dt.UTC)
    HIGH = dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.UTC)

    def test_persists_storage_rows_exactly(self) -> None:
        response = _response(
            [],
            self.LOW,
            self.HIGH,
            storage_rows=[_storage_row(dt.date(2026, 7, 7), gib_seconds="8381903.171539306640625")],
        )

        replace_window(response)

        stored = DuckgresDailyStorageUsage.objects.get()
        assert stored.date == dt.date(2026, 7, 7)
        assert str(stored.organization_id) == ORG
        assert stored.team_id == 42
        assert stored.gib_seconds == Decimal("8381903.171539306640625")

    def test_both_families_replace_in_one_window(self) -> None:
        # Pre-existing rows for the open day in BOTH tables must be replaced together.
        _seed(dt.date(2026, 7, 7), cpu_seconds=1)
        DuckgresDailyStorageUsage.objects.create(
            date=dt.date(2026, 7, 7), organization_id=ORG, team_id=42, gib_seconds=Decimal("1")
        )
        response = _response(
            [_row(dt.date(2026, 7, 7), cpu_seconds=500)],
            self.LOW,
            self.HIGH,
            storage_rows=[_storage_row(dt.date(2026, 7, 7), gib_seconds="777")],
        )

        replace_window(response)

        assert DuckgresDailyUsage.objects.get(date=dt.date(2026, 7, 7)).cpu_seconds == 500
        assert DuckgresDailyStorageUsage.objects.get(date=dt.date(2026, 7, 7)).gib_seconds == Decimal("777")

    def test_storage_only_window_still_replaces_compute(self) -> None:
        # A day whose compute went silent but storage persists: compute rows for
        # the window must still be dropped even when only storage rows arrive.
        _seed(dt.date(2026, 7, 7), cpu_seconds=999)
        response = _response([], self.LOW, self.HIGH, storage_rows=[_storage_row(dt.date(2026, 7, 7))])

        replace_window(response)

        assert not DuckgresDailyUsage.objects.filter(date=dt.date(2026, 7, 7)).exists()
        assert DuckgresDailyStorageUsage.objects.filter(date=dt.date(2026, 7, 7)).count() == 1

    def test_preserves_acked_storage_days(self) -> None:
        DuckgresDailyStorageUsage.objects.create(
            date=dt.date(2026, 7, 6), organization_id=ORG, team_id=42, gib_seconds=Decimal("360000")
        )
        response = _response([], self.LOW, self.HIGH, storage_rows=[_storage_row(dt.date(2026, 7, 7))])

        replace_window(response)

        assert DuckgresDailyStorageUsage.objects.filter(date=dt.date(2026, 7, 6)).count() == 1

    def test_returns_total_rows_written_across_families(self) -> None:
        response = _response(
            [_row(dt.date(2026, 7, 7))],
            self.LOW,
            self.HIGH,
            storage_rows=[_storage_row(dt.date(2026, 7, 7))],
        )

        assert replace_window(response) == 2
