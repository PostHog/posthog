from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from posthog.dataclasses import frozen

from products.ai_observability.backend.logic.docs_urls import COST_DOCS_URL, INSTALLATION_DOCS_URL, SESSIONS_DOCS_URL
from products.ai_observability.backend.logic.instrumentation.signals import (
    FIRST_EVENT_FLOOR,
    SignalGrade,
    answers_session,
    grade_signal,
)
from products.ai_observability.backend.logic.traces.trace_selection import TraceWindow, shift

HOURLY_BUCKET_MAX_SPAN = timedelta(days=2)
# The bucket list is built in memory before ClickHouse runs, where no query timeout bounds it, so a range with more
# buckets than this is refused as too long. That is over a century of days, far past any range a person reads.
MAX_BUCKETS = 40_000


class MetricKey(StrEnum):
    COST = "cost"
    USERS = "users"
    SESSIONS = "sessions"
    TRACES = "traces"
    ERROR_RATE = "error_rate"
    P95_LATENCY = "p95_latency"


class ChangeUnit(StrEnum):
    PERCENT = "percent"
    POINTS = "points"
    SECONDS = "seconds"


class ChangeTone(StrEnum):
    GOOD = "good"
    BAD = "bad"
    NEUTRAL = "neutral"


class TileStatus(StrEnum):
    OK = "ok"
    NOT_SET_UP = "not_set_up"


class BucketSize(StrEnum):
    HOUR = "hour"
    DAY = "day"


@frozen
class PeriodTotals:
    traces: int
    errored: int
    cost: float
    sessions: int
    users: int
    p50_latency_s: float | None
    p95_latency_s: float | None
    p99_latency_s: float | None
    traces_with_cost: int
    traces_with_latency: int
    traces_with_session: int
    session_declines: int
    identified_generations: int
    non_otel_generations: int


NO_TRACES = PeriodTotals(
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


@frozen
class SetupGuide:
    label: str
    docs_url: str


@frozen
class LatencyQuantiles:
    p50_s: float
    p99_s: float


@frozen
class Tile:
    key: MetricKey
    label: str
    value: float | None
    previous: float | None
    change: float | None
    change_unit: ChangeUnit
    change_tone: ChangeTone
    status: TileStatus
    setup: SetupGuide | None
    detail: str | None
    latency_quantiles: LatencyQuantiles | None
    series: list[float | None]


@frozen
class _MetricSpec:
    label: str
    change_unit: ChangeUnit
    rising_is_bad: bool = False
    setup: SetupGuide | None = None


_METRICS = {
    MetricKey.COST: _MetricSpec(
        label="Cost",
        change_unit=ChangeUnit.PERCENT,
        setup=SetupGuide(label="Track costs", docs_url=COST_DOCS_URL),
    ),
    MetricKey.USERS: _MetricSpec(
        label="Users",
        change_unit=ChangeUnit.PERCENT,
        setup=SetupGuide(label="Identify users", docs_url=INSTALLATION_DOCS_URL),
    ),
    MetricKey.SESSIONS: _MetricSpec(
        label="Sessions",
        change_unit=ChangeUnit.PERCENT,
        setup=SetupGuide(label="Add session IDs", docs_url=SESSIONS_DOCS_URL),
    ),
    MetricKey.TRACES: _MetricSpec(label="Traces", change_unit=ChangeUnit.PERCENT),
    MetricKey.ERROR_RATE: _MetricSpec(label="Error rate", change_unit=ChangeUnit.POINTS, rising_is_bad=True),
    MetricKey.P95_LATENCY: _MetricSpec(
        label="p95 latency",
        change_unit=ChangeUnit.SECONDS,
        rising_is_bad=True,
        setup=SetupGuide(label="Capture latency", docs_url=INSTALLATION_DOCS_URL),
    ),
}


def previous_window(window: TraceWindow) -> TraceWindow:
    length = window.end.astimezone(UTC) - window.start.astimezone(UTC)
    return TraceWindow(start=shift(window.start, -length), end=window.start)


def bucket_size_for(window: TraceWindow) -> BucketSize:
    return (
        BucketSize.HOUR
        if window.end.astimezone(UTC) - window.start.astimezone(UTC) <= HOURLY_BUCKET_MAX_SPAN
        else BucketSize.DAY
    )


def has_too_many_buckets(window: TraceWindow, size: BucketSize) -> bool:
    length = timedelta(hours=1) if size == BucketSize.HOUR else timedelta(days=1)
    return (window.end.astimezone(UTC) - window.start.astimezone(UTC)) / length > MAX_BUCKETS


def has_no_previous_window(window: TraceWindow) -> bool:
    """Whether the period before the window would start before the first representable date, as for a window starting
    in year 1."""
    try:
        previous_window(window)
    except OverflowError:
        return True
    return False


def bucket_floor(moment: datetime, size: BucketSize) -> datetime:
    if size == BucketSize.HOUR:
        return moment.replace(minute=0, second=0, microsecond=0)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def bucket_starts(window: TraceWindow, size: BucketSize) -> list[datetime]:
    zone = window.start.tzinfo
    first = bucket_floor(window.start, size)
    if size == BucketSize.HOUR:

        def next_start(moment: datetime) -> datetime:
            return (moment.astimezone(UTC) + timedelta(hours=1)).astimezone(zone)
    else:

        def next_start(moment: datetime) -> datetime:
            return datetime.combine(moment.date() + timedelta(days=1), moment.time(), tzinfo=zone)

    starts = []
    moment = first
    while moment.astimezone(UTC) < window.end.astimezone(UTC):
        starts.append(moment)
        moment = next_start(moment)
    return starts


def metric_value(totals: PeriodTotals, key: MetricKey) -> float | None:
    match key:
        case MetricKey.COST:
            return totals.cost
        case MetricKey.USERS:
            return totals.users
        case MetricKey.SESSIONS:
            return totals.sessions
        case MetricKey.TRACES:
            return totals.traces
        case MetricKey.ERROR_RATE:
            return totals.errored / totals.traces if totals.traces else None
        case MetricKey.P95_LATENCY:
            return totals.p95_latency_s


def _change(value: float | None, previous: float | None, unit: ChangeUnit) -> float | None:
    if value is None or previous is None:
        return None
    match unit:
        case ChangeUnit.PERCENT:
            return (value - previous) / previous * 100 if previous else None
        case ChangeUnit.POINTS:
            return (value - previous) * 100
        case ChangeUnit.SECONDS:
            return value - previous


def _tone(change: float | None, spec: _MetricSpec) -> ChangeTone:
    if not spec.rising_is_bad or not change:
        return ChangeTone.NEUTRAL
    return ChangeTone.BAD if change > 0 else ChangeTone.GOOD


def _count(value: float) -> str:
    return f"{value:,.0f}" if value >= 10 else f"{value:.1f}".removesuffix(".0")


def _detail(totals: PeriodTotals, key: MetricKey, window: TraceWindow) -> str | None:
    match key:
        case MetricKey.COST:
            return "Spend across all models"
        case MetricKey.USERS:
            return "Identified people with at least one trace"
        case MetricKey.SESSIONS:
            if not totals.sessions:
                return None
            return f"{totals.traces_with_session / totals.sessions:.1f} traces per session"
        case MetricKey.TRACES:
            # Averaging over the bucket the chart shows keeps a short range from extrapolating to a whole day.
            per, length = (
                ("hour", timedelta(hours=1))
                if bucket_size_for(window) == BucketSize.HOUR
                else ("day", timedelta(days=1))
            )
            units = (window.end.astimezone(UTC) - window.start.astimezone(UTC)) / length
            return f"{_count(totals.traces / units)} per {per} on average" if units > 0 else None
        case MetricKey.ERROR_RATE:
            return f"{totals.errored:,} errored trace{'' if totals.errored == 1 else 's'}"
        case MetricKey.P95_LATENCY:
            return None


def _latency_quantiles(totals: PeriodTotals, key: MetricKey) -> LatencyQuantiles | None:
    if key != MetricKey.P95_LATENCY or totals.p50_latency_s is None or totals.p99_latency_s is None:
        return None
    return LatencyQuantiles(p50_s=totals.p50_latency_s, p99_s=totals.p99_latency_s)


def _status(totals: PeriodTotals, key: MetricKey) -> TileStatus:
    if totals.traces == 0:
        return TileStatus.OK
    match key:
        case MetricKey.COST:
            missing = totals.traces_with_cost == 0
        case MetricKey.P95_LATENCY:
            missing = totals.traces_with_latency == 0
        case MetricKey.SESSIONS:
            missing = not answers_session(
                with_session=totals.traces_with_session, declining_session=totals.session_declines
            )
        case MetricKey.USERS:
            missing = (
                grade_signal(
                    events=totals.non_otel_generations,
                    floor=FIRST_EVENT_FLOOR,
                    has_signal=totals.identified_generations > 0,
                )
                == SignalGrade.MISSING
            )
        case _:
            missing = False
    return TileStatus.NOT_SET_UP if missing else TileStatus.OK


def tiles_of(
    current: PeriodTotals,
    previous: PeriodTotals | None,
    buckets: Mapping[datetime, PeriodTotals],
    starts: Sequence[datetime],
    window: TraceWindow,
) -> list[Tile]:
    """One tile per metric over `window`, with its series over `starts`. `buckets` is keyed by each bucket's start in
    UTC, and a start with no bucket had no traces."""
    # Python never finds two datetimes equal across zones in the hour a clock goes back, so both sides meet in UTC.
    aligned = [buckets.get(start.astimezone(UTC), NO_TRACES) for start in starts]
    tiles = []
    for key, spec in _METRICS.items():
        value = metric_value(current, key)
        previous_value = metric_value(previous, key) if previous is not None else None
        change = _change(value, previous_value, spec.change_unit)
        status = _status(current, key)
        tiles.append(
            Tile(
                key=key,
                label=spec.label,
                value=value,
                previous=previous_value,
                change=change,
                change_unit=spec.change_unit,
                change_tone=_tone(change, spec),
                status=status,
                setup=spec.setup if status == TileStatus.NOT_SET_UP else None,
                detail=_detail(current, key, window),
                latency_quantiles=_latency_quantiles(current, key),
                series=[metric_value(totals, key) for totals in aligned],
            )
        )
    return tiles
