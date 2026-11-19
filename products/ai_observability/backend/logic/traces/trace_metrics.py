from datetime import UTC, datetime, timedelta
from enum import StrEnum

from posthog.dataclasses import frozen

from products.ai_observability.backend.logic.traces.trace_selection import TraceWindow

HOURLY_BUCKET_MAX_SPAN = timedelta(days=2)


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
    p95_latency_s: float | None
    traces_with_cost: int
    traces_with_latency: int
    traces_with_session: int
    identified_events: int
    non_otel_generations: int


@frozen
class Tile:
    key: MetricKey
    value: float | None
    previous: float | None
    change: float | None
    change_unit: ChangeUnit
    status: TileStatus


_CHANGE_UNITS = {
    MetricKey.COST: ChangeUnit.PERCENT,
    MetricKey.USERS: ChangeUnit.PERCENT,
    MetricKey.SESSIONS: ChangeUnit.PERCENT,
    MetricKey.TRACES: ChangeUnit.PERCENT,
    MetricKey.ERROR_RATE: ChangeUnit.POINTS,
    MetricKey.P95_LATENCY: ChangeUnit.SECONDS,
}


def bucket_size_for(window: TraceWindow) -> BucketSize:
    return BucketSize.HOUR if window.end - window.start <= HOURLY_BUCKET_MAX_SPAN else BucketSize.DAY


def bucket_starts(window: TraceWindow, size: BucketSize) -> list[datetime]:
    zone = window.start.tzinfo
    if size == BucketSize.HOUR:
        first = window.start.replace(minute=0, second=0, microsecond=0)
        step = timedelta(hours=1)
        next_start = lambda moment: (moment.astimezone(UTC) + step).astimezone(zone)  # noqa: E731
    else:
        first = window.start.replace(hour=0, minute=0, second=0, microsecond=0)
        next_start = lambda moment: datetime.combine(  # noqa: E731
            moment.date() + timedelta(days=1), moment.time(), tzinfo=zone
        )
    starts = []
    moment = first
    while moment < window.end:
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


def _status(totals: PeriodTotals, key: MetricKey) -> TileStatus:
    if totals.traces == 0:
        return TileStatus.OK
    match key:
        case MetricKey.COST:
            missing = totals.traces_with_cost == 0
        case MetricKey.P95_LATENCY:
            missing = totals.traces_with_latency == 0
        case MetricKey.SESSIONS:
            missing = totals.traces_with_session == 0
        case MetricKey.USERS:
            missing = totals.identified_events == 0 and totals.non_otel_generations > 0
        case _:
            missing = False
    return TileStatus.NOT_SET_UP if missing else TileStatus.OK


def tiles_of(current: PeriodTotals, previous: PeriodTotals | None) -> list[Tile]:
    tiles = []
    for key in MetricKey:
        value = metric_value(current, key)
        previous_value = metric_value(previous, key) if previous is not None else None
        tiles.append(
            Tile(
                key=key,
                value=value,
                previous=previous_value,
                change=_change(value, previous_value, _CHANGE_UNITS[key]),
                change_unit=_CHANGE_UNITS[key],
                status=_status(current, key),
            )
        )
    return tiles
