from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from parameterized import parameterized

from products.ai_observability.backend.logic.docs_urls import COST_DOCS_URL, INSTALLATION_DOCS_URL, SESSIONS_DOCS_URL
from products.ai_observability.backend.logic.traces.trace_metrics import (
    BucketSize,
    ChangeTone,
    ChangeUnit,
    LatencyQuantiles,
    MetricKey,
    PeriodTotals,
    SetupGuide,
    Tile,
    TileStatus,
    bucket_size_for,
    bucket_starts,
    previous_window,
    tiles_of,
)
from products.ai_observability.backend.logic.traces.trace_selection import TraceWindow

FULL = PeriodTotals(
    traces=100,
    errored=10,
    cost=50.0,
    sessions=20,
    users=5,
    p50_latency_s=1.5,
    p95_latency_s=4.0,
    p99_latency_s=8.25,
    traces_with_cost=100,
    traces_with_latency=100,
    traces_with_session=100,
    session_declines=0,
    identified_generations=100,
    non_otel_generations=100,
)
EMPTY = PeriodTotals(
    traces=0,
    errored=0,
    cost=0.0,
    sessions=0,
    users=0,
    p50_latency_s=None,
    p95_latency_s=None,
    p99_latency_s=None,
    traces_with_cost=0,
    traces_with_latency=0,
    traces_with_session=0,
    session_declines=0,
    identified_generations=0,
    non_otel_generations=0,
)
START = datetime(2026, 9, 1, 10, 30, tzinfo=UTC)
WEEK = TraceWindow(start=START, end=START + timedelta(days=7))
DAY = TraceWindow(start=START, end=START + timedelta(days=1))


def tile(tiles: list[Tile], key: MetricKey) -> Tile:
    return next(t for t in tiles if t.key == key)


def totals_tiles(current: PeriodTotals, previous: PeriodTotals | None) -> list[Tile]:
    return tiles_of(current, previous, {}, [], WEEK)


def test_tiles_come_in_metric_key_order() -> None:
    assert [t.key for t in totals_tiles(FULL, None)] == list(MetricKey)


def test_change_is_null_when_previous_is_zero() -> None:
    previous = replace(FULL, cost=0.0)
    cost = tile(totals_tiles(FULL, previous), MetricKey.COST)
    assert (cost.value, cost.previous, cost.change, cost.change_unit) == (50.0, 0.0, None, ChangeUnit.PERCENT)


def test_percent_change_and_missing_previous_period() -> None:
    assert tile(totals_tiles(FULL, replace(FULL, cost=25.0)), MetricKey.COST).change == 100.0
    assert tile(totals_tiles(FULL, None), MetricKey.COST).change is None


def test_error_rate_change_is_in_points() -> None:
    previous = replace(FULL, errored=5)
    error_rate = tile(totals_tiles(FULL, previous), MetricKey.ERROR_RATE)
    assert (error_rate.value, error_rate.previous, error_rate.change_unit) == (0.1, 0.05, ChangeUnit.POINTS)
    assert error_rate.change is not None
    assert round(error_rate.change, 9) == 5.0


def test_p95_change_is_in_seconds() -> None:
    p95 = tile(totals_tiles(FULL, replace(FULL, p95_latency_s=3.0)), MetricKey.P95_LATENCY)
    assert (p95.change, p95.change_unit) == (1.0, ChangeUnit.SECONDS)


@parameterized.expand(
    [
        ("error rate up", MetricKey.ERROR_RATE, replace(FULL, errored=5), ChangeTone.BAD),
        ("error rate down", MetricKey.ERROR_RATE, replace(FULL, errored=20), ChangeTone.GOOD),
        ("p95 up", MetricKey.P95_LATENCY, replace(FULL, p95_latency_s=3.0), ChangeTone.BAD),
        ("p95 down", MetricKey.P95_LATENCY, replace(FULL, p95_latency_s=5.0), ChangeTone.GOOD),
        ("p95 unchanged", MetricKey.P95_LATENCY, FULL, ChangeTone.NEUTRAL),
        ("p95 with no previous value", MetricKey.P95_LATENCY, replace(FULL, p95_latency_s=None), ChangeTone.NEUTRAL),
        ("cost up", MetricKey.COST, replace(FULL, cost=25.0), ChangeTone.NEUTRAL),
        ("traces down", MetricKey.TRACES, replace(FULL, traces=200), ChangeTone.NEUTRAL),
    ]
)
def test_change_tone(_name: str, key: MetricKey, previous: PeriodTotals, expected: ChangeTone) -> None:
    assert tile(totals_tiles(FULL, previous), key).change_tone == expected


def test_series_follow_the_bucket_starts_with_gaps_as_no_traces() -> None:
    starts = [START + timedelta(hours=hour) for hour in range(3)]
    busy = replace(FULL, traces=4, errored=1)

    tiles = tiles_of(FULL, None, {starts[1]: busy}, starts, WEEK)

    assert tile(tiles, MetricKey.TRACES).series == [0, 4, 0]
    assert tile(tiles, MetricKey.ERROR_RATE).series == [None, 0.25, None]


def test_series_find_both_buckets_of_the_hour_the_clock_goes_back() -> None:
    zone = ZoneInfo("Europe/Madrid")
    window = TraceWindow(
        start=datetime(2026, 10, 25, 1, 30, tzinfo=zone), end=datetime(2026, 10, 25, 3, 30, tzinfo=zone)
    )
    starts = bucket_starts(window, BucketSize.HOUR)
    # A cached read keys its buckets with fixed offsets, as JSON carries them.
    first, second = (start.astimezone(timezone(start.utcoffset() or timedelta())) for start in starts[1:3])

    tiles = tiles_of(FULL, None, {first: replace(FULL, traces=2), second: replace(FULL, traces=3)}, starts, window)

    assert tile(tiles, MetricKey.TRACES).series == [0, 2, 3, 0]


@parameterized.expand(
    [
        ("cost", MetricKey.COST, FULL, "Spend across all models"),
        ("users", MetricKey.USERS, FULL, "Identified people with at least one trace"),
        ("sessions", MetricKey.SESSIONS, replace(FULL, traces_with_session=70), "3.5 traces per session"),
        ("no sessions", MetricKey.SESSIONS, replace(FULL, sessions=0, traces_with_session=0), None),
        ("traces", MetricKey.TRACES, replace(FULL, traces=7700), "1,100 per day on average"),
        ("few traces", MetricKey.TRACES, replace(FULL, traces=3), "0.4 per day on average"),
        ("one trace a day", MetricKey.TRACES, replace(FULL, traces=7), "1 per day on average"),
        ("traces over hourly buckets", MetricKey.TRACES, replace(FULL, traces=48), "2 per hour on average", DAY),
        ("errored traces", MetricKey.ERROR_RATE, replace(FULL, errored=1204), "1,204 errored traces"),
        ("one errored trace", MetricKey.ERROR_RATE, replace(FULL, errored=1), "1 errored trace"),
        ("latency", MetricKey.P95_LATENCY, FULL, None),
    ]
)
def test_detail_line(
    _name: str, key: MetricKey, totals: PeriodTotals, expected: str | None, window: TraceWindow = WEEK
) -> None:
    assert tile(tiles_of(totals, None, {}, [], window), key).detail == expected


@parameterized.expand(
    [
        ("latency", MetricKey.P95_LATENCY, FULL, LatencyQuantiles(p50_s=1.5, p99_s=8.25)),
        ("no latency", MetricKey.P95_LATENCY, replace(FULL, p50_latency_s=None, p99_latency_s=None), None),
        ("another tile", MetricKey.TRACES, FULL, None),
    ]
)
def test_latency_quantiles(_name: str, key: MetricKey, totals: PeriodTotals, expected: LatencyQuantiles | None) -> None:
    assert tile(tiles_of(totals, None, {}, [], WEEK), key).latency_quantiles == expected


def test_cost_not_set_up_when_no_trace_has_cost() -> None:
    tiles = totals_tiles(replace(FULL, traces_with_cost=0, cost=0.0), None)
    assert tile(tiles, MetricKey.COST).status == TileStatus.NOT_SET_UP
    assert tile(tiles, MetricKey.TRACES).status == TileStatus.OK


@parameterized.expand(
    [
        (MetricKey.COST, "traces_with_cost", SetupGuide(label="Track costs", docs_url=COST_DOCS_URL)),
        (
            MetricKey.P95_LATENCY,
            "traces_with_latency",
            SetupGuide(label="Capture latency", docs_url=INSTALLATION_DOCS_URL),
        ),
        (MetricKey.SESSIONS, "traces_with_session", SetupGuide(label="Add session IDs", docs_url=SESSIONS_DOCS_URL)),
    ]
)
def test_coverage_decides_not_set_up_and_its_setup_guide(key: MetricKey, field: str, setup: SetupGuide) -> None:
    missing = tile(totals_tiles(replace(FULL, **{field: 0}), None), key)
    covered = tile(totals_tiles(replace(FULL, **{field: 1}), None), key)
    assert (missing.status, missing.setup) == (TileStatus.NOT_SET_UP, setup)
    assert (covered.status, covered.setup) == (TileStatus.OK, None)


def test_tiles_ok_when_range_is_empty() -> None:
    tiles = totals_tiles(EMPTY, EMPTY)
    assert all(t.status == TileStatus.OK for t in tiles)
    assert all(t.value in (0, None) for t in tiles)
    assert tile(tiles, MetricKey.ERROR_RATE).value is None


def test_sessions_set_up_when_traces_decline_a_session() -> None:
    totals = replace(FULL, traces_with_session=0, session_declines=3)
    assert tile(totals_tiles(totals, None), MetricKey.SESSIONS).status == TileStatus.OK


def test_users_status_ok_when_every_generation_is_otel() -> None:
    totals = replace(FULL, identified_generations=0, non_otel_generations=0)
    assert tile(totals_tiles(totals, None), MetricKey.USERS).status == TileStatus.OK


def test_users_not_set_up_when_no_generation_is_identified() -> None:
    totals = replace(FULL, identified_generations=0, non_otel_generations=3)
    users = tile(totals_tiles(totals, None), MetricKey.USERS)
    assert (users.status, users.setup) == (
        TileStatus.NOT_SET_UP,
        SetupGuide(label="Identify users", docs_url=INSTALLATION_DOCS_URL),
    )


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


def test_previous_window_has_the_same_length_and_ends_at_the_window_start() -> None:
    madrid = ZoneInfo("Europe/Madrid")
    # Clocks go back an hour that night, so the window spans 13 hours though its wall clock reads 12.
    window = TraceWindow(
        start=datetime(2026, 10, 25, 0, 0, tzinfo=madrid), end=datetime(2026, 10, 25, 12, 0, tzinfo=madrid)
    )

    assert previous_window(window) == TraceWindow(start=datetime(2026, 10, 24, 11, 0, tzinfo=madrid), end=window.start)
