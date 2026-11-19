from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.trace_metrics import (
    BucketSize,
    ChangeUnit,
    MetricKey,
    PeriodTotals,
    Tile,
    TileStatus,
    bucket_size_for,
    bucket_starts,
    tiles_of,
)
from products.ai_observability.backend.logic.traces.trace_selection import TraceWindow

FULL = PeriodTotals(
    traces=100,
    errored=10,
    cost=50.0,
    sessions=20,
    users=5,
    p95_latency_s=4.0,
    traces_with_cost=100,
    traces_with_latency=100,
    traces_with_session=100,
    identified_events=100,
    non_otel_generations=100,
)
EMPTY = PeriodTotals(
    traces=0,
    errored=0,
    cost=0.0,
    sessions=0,
    users=0,
    p95_latency_s=None,
    traces_with_cost=0,
    traces_with_latency=0,
    traces_with_session=0,
    identified_events=0,
    non_otel_generations=0,
)
START = datetime(2026, 9, 1, 10, 30, tzinfo=UTC)


def tile(tiles: list[Tile], key: MetricKey) -> Tile:
    return next(t for t in tiles if t.key == key)


def test_tiles_come_in_metric_key_order() -> None:
    assert [t.key for t in tiles_of(FULL, None)] == list(MetricKey)


def test_change_is_null_when_previous_is_zero() -> None:
    previous = replace(FULL, cost=0.0)
    cost = tile(tiles_of(FULL, previous), MetricKey.COST)
    assert (cost.value, cost.previous, cost.change, cost.change_unit) == (50.0, 0.0, None, ChangeUnit.PERCENT)


def test_percent_change_and_missing_previous_period() -> None:
    assert tile(tiles_of(FULL, replace(FULL, cost=25.0)), MetricKey.COST).change == 100.0
    assert tile(tiles_of(FULL, None), MetricKey.COST).change is None


def test_error_rate_change_is_in_points() -> None:
    previous = replace(FULL, errored=5)
    error_rate = tile(tiles_of(FULL, previous), MetricKey.ERROR_RATE)
    assert (error_rate.value, error_rate.previous, error_rate.change_unit) == (0.1, 0.05, ChangeUnit.POINTS)
    assert error_rate.change is not None
    assert round(error_rate.change, 9) == 5.0


def test_p95_change_is_in_seconds() -> None:
    p95 = tile(tiles_of(FULL, replace(FULL, p95_latency_s=3.0)), MetricKey.P95_LATENCY)
    assert (p95.change, p95.change_unit) == (1.0, ChangeUnit.SECONDS)


def test_cost_not_set_up_when_no_trace_has_cost() -> None:
    tiles = tiles_of(replace(FULL, traces_with_cost=0, cost=0.0), None)
    assert tile(tiles, MetricKey.COST).status == TileStatus.NOT_SET_UP
    assert tile(tiles, MetricKey.TRACES).status == TileStatus.OK


@parameterized.expand(
    [
        (MetricKey.COST, "traces_with_cost"),
        (MetricKey.P95_LATENCY, "traces_with_latency"),
        (MetricKey.SESSIONS, "traces_with_session"),
    ]
)
def test_coverage_decides_not_set_up(key: MetricKey, field: str) -> None:
    assert tile(tiles_of(replace(FULL, **{field: 0}), None), key).status == TileStatus.NOT_SET_UP
    assert tile(tiles_of(replace(FULL, **{field: 1}), None), key).status == TileStatus.OK


def test_tiles_ok_when_range_is_empty() -> None:
    tiles = tiles_of(EMPTY, EMPTY)
    assert all(t.status == TileStatus.OK for t in tiles)
    assert all(t.value in (0, None) for t in tiles)
    assert tile(tiles, MetricKey.ERROR_RATE).value is None


def test_users_status_ok_when_every_generation_is_otel() -> None:
    totals = replace(FULL, identified_events=0, non_otel_generations=0)
    assert tile(tiles_of(totals, None), MetricKey.USERS).status == TileStatus.OK


def test_users_not_set_up_when_no_event_is_identified() -> None:
    totals = replace(FULL, identified_events=0, non_otel_generations=3)
    assert tile(tiles_of(totals, None), MetricKey.USERS).status == TileStatus.NOT_SET_UP


@parameterized.expand(
    [
        (timedelta(hours=1), BucketSize.HOUR),
        (timedelta(hours=48), BucketSize.HOUR),
        (timedelta(hours=48, seconds=1), BucketSize.DAY),
        (timedelta(days=30), BucketSize.DAY),
    ]
)
def test_bucket_size_hour_up_to_two_days_day_beyond(span: timedelta, expected: BucketSize) -> None:
    assert bucket_size_for(TraceWindow(start=START, end=START + span)) == expected


def test_bucket_starts_cover_the_window() -> None:
    window = TraceWindow(start=START, end=START + timedelta(hours=3))
    assert bucket_starts(window, BucketSize.HOUR) == [
        datetime(2026, 9, 1, 10, tzinfo=UTC),
        datetime(2026, 9, 1, 11, tzinfo=UTC),
        datetime(2026, 9, 1, 12, tzinfo=UTC),
        datetime(2026, 9, 1, 13, tzinfo=UTC),
    ]


def test_day_buckets_start_at_midnight_in_the_window_zone_across_dst() -> None:
    zone = ZoneInfo("Europe/Madrid")
    window = TraceWindow(
        start=datetime(2026, 10, 24, 15, tzinfo=zone),
        end=datetime(2026, 10, 27, 1, tzinfo=zone),
    )
    starts = bucket_starts(window, BucketSize.DAY)
    assert [s.replace(tzinfo=None) for s in starts] == [datetime(2026, 10, d) for d in (24, 25, 26, 27)]
    assert all(s.tzinfo == zone for s in starts)
    assert starts[2].astimezone(UTC) - starts[1].astimezone(UTC) == timedelta(hours=25)


def test_hour_buckets_stay_one_real_hour_apart_across_dst() -> None:
    zone = ZoneInfo("Europe/Madrid")
    window = TraceWindow(
        start=datetime(2026, 10, 25, 0, 30, tzinfo=zone),
        end=datetime(2026, 10, 25, 5, 0, tzinfo=zone),
    )
    starts = bucket_starts(window, BucketSize.HOUR)
    assert all(s.tzinfo == zone for s in starts)
    gaps = {(b.astimezone(UTC) - a.astimezone(UTC)) for a, b in zip(starts, starts[1:])}
    assert gaps == {timedelta(hours=1)}
    assert len(starts) == 6


def test_bucket_size_measures_real_elapsed_time_across_dst() -> None:
    zone = ZoneInfo("Europe/Madrid")
    window = TraceWindow(
        start=datetime(2026, 10, 24, 12, tzinfo=zone),
        end=datetime(2026, 10, 26, 12, tzinfo=zone),
    )
    assert bucket_size_for(window) == BucketSize.DAY
