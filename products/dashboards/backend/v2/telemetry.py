"""PromQL and LogQL targets of the `dashboard-v2` query batch.

A PromQL target runs as a `MetricsQuery` in PromQL mode, so it is cached, planned and limited like any other
`/query` call, and it reads precomputed metrics where they cover it. LogQL has no query runner, so a LogQL target
goes to Snuffle's Loki API on every run, uncached, under the same telemetry limit that metrics tiles wait in.

Both pick their step the way Grafana and Dash do: the smallest step on the metrics interval ladder that keeps the
range under the panel's max data points, never below the panel's min interval or, for PromQL, the scrape interval.
A relative range has the same span on every refresh, so it gets the same step and the same cache key.
"""

import re
import json
import math
import asyncio
from datetime import UTC, datetime, timedelta, tzinfo
from threading import Event
from typing import Any, Optional

from django.conf import settings
from django.utils.timezone import now

import httpx
import structlog
from dateutil.relativedelta import relativedelta

from posthog.api.snuffle_proxy import SNUFFLE_API_FEATURE_FLAG, SnuffleNotConfiguredError, snuffle_stream
from posthog.api_queries_budget import BudgetSpec, budget_enabled, budget_spec_for, refill_and_read
from posthog.clickhouse.client.limit import get_app_telemetry_queries_rate_limiter
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import api_queries_budget_enforcement_enabled
from posthog.models.team import Team
from posthog.models.team.team_event_volume import events_last_year_for
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled, user_can_access_resource

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError

logger = structlog.get_logger(__name__)

_STEPS: tuple[tuple[str, int, str], ...] = (
    ("15s", 15, "second_15"),
    ("30s", 30, "second_30"),
    ("1m", 60, "minute"),
    ("5m", 300, "minute_5"),
    ("15m", 900, "minute_15"),
    ("30m", 1800, "minute_30"),
    ("1h", 3600, "hour"),
    ("6h", 21600, "hour_6"),
    ("1d", 86400, "day"),
    ("1w", 604800, "week"),
)
# PostHog ingests metrics once a minute, so a shorter PromQL step only repeats points.
SCRAPE_SECONDS = 60
DEFAULT_MAX_DATA_POINTS = 300
LOG_LINE_LIMIT = 1000
# A metric LogQL query's `limit` caps log lines, not series, so the response body is capped as it streams in.
MAX_LOGQL_RESPONSE_BYTES = 32 * 1024 * 1024
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_DURATION = re.compile(r"(\d+)([smhdw])")
_RELATIVE = re.compile(r"now-(\d{1,9})([smhdwMy])")
_METRIC_LOGQL = re.compile(r"\b(\w+_over_time|rate|bytes_rate|rate_counter)\s*\(")


class TelemetryTargetError(ValueError):
    """A PromQL or LogQL target that cannot run. The message is safe to show."""


def _parse_time(expression: str, at: datetime, tz: tzinfo) -> datetime:
    """A time expression as a UTC moment. Months and years are calendar months and years in the project's
    timezone, and an ISO date without an offset is in that timezone, as `MetricsQuery` reads them, so a PromQL
    and a LogQL panel with one range read the same window. Fixed durations count elapsed time, so they are
    subtracted in UTC: across a DST change, wall-clock arithmetic would put `now-30m` after `now`."""
    at = at.astimezone(UTC)
    if expression == "now":
        return at
    try:
        if match := _RELATIVE.fullmatch(expression):
            amount, unit = int(match.group(1)), match.group(2)
            if unit in ("M", "y"):
                delta = relativedelta(months=amount) if unit == "M" else relativedelta(years=amount)
                return (at.astimezone(tz) - delta).astimezone(UTC)
            return at - timedelta(seconds=amount * _UNIT_SECONDS[unit])
        parsed = datetime.fromisoformat(expression)
    except (ValueError, OverflowError):
        raise TelemetryTargetError(f"Unsupported time expression: {expression!r}.")
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)).astimezone(UTC)


@frozen
class TimeRange:
    start: datetime
    end: datetime


@frozen
class Step:
    seconds: int
    interval: str
    """The `MetricsQuery` interval with this step."""


def time_range(date_from: str, date_to: str, *, tz: tzinfo = UTC, at: Optional[datetime] = None) -> TimeRange:
    at = at or now()
    start, end = _parse_time(date_from, at, tz), _parse_time(date_to, at, tz)
    if end <= start:
        raise TelemetryTargetError("The time range ends before it starts.")
    return TimeRange(start=start, end=end)


def _min_interval_seconds(interval: Optional[str]) -> int:
    if not interval:
        return 0
    match = _DURATION.fullmatch(interval)
    if match is None:
        raise TelemetryTargetError(f"Unsupported interval: {interval!r}. Use a duration such as 1m, 5m or 1h.")
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def pick_step(span: timedelta, *, max_data_points: Optional[int], min_interval: Optional[str], is_promql: bool) -> Step:
    points = max(1, max_data_points or DEFAULT_MAX_DATA_POINTS)
    floor = max(_min_interval_seconds(min_interval), SCRAPE_SECONDS if is_promql else 0)
    for _duration, seconds, name in _STEPS:
        if seconds >= floor and span.total_seconds() / seconds <= points:
            return Step(seconds=seconds, interval=name)
    if is_promql:
        # A `MetricsQuery` interval stops at a week, so a coarser step cannot be honoured.
        raise TelemetryTargetError(
            "The range needs a step longer than 1w. Shorten the range, raise max data points or lower the interval."
        )
    # Loki takes any step, so past the ladder the step is whatever keeps both constraints.
    return Step(seconds=max(floor, math.ceil(span.total_seconds() / points)), interval="")


def promql_interval(
    date_from: str, date_to: str, *, max_data_points: Optional[int], min_interval: Optional[str], tz: tzinfo = UTC
) -> str:
    window = time_range(date_from, date_to, tz=tz)
    span = window.end - window.start
    return pick_step(span, max_data_points=max_data_points, min_interval=min_interval, is_promql=True).interval


def _without_strings(logql: str) -> str:
    """The query with the contents of its double-quoted and backtick strings removed, in one linear pass."""
    kept: list[str] = []
    quote: Optional[str] = None
    escaped = False
    for char in logql:
        if quote is None:
            kept.append(char)
            if char in ('"', "`"):
                quote = char
        elif escaped:
            escaped = False
        elif char == "\\" and quote == '"':
            escaped = True
        elif char == quote:
            kept.append(char)
            quote = None
    return "".join(kept)


def returns_log_lines(logql: str) -> bool:
    return bool(logql.strip()) and _METRIC_LOGQL.search(_without_strings(logql)) is None


def _align(moment: datetime, step: int) -> datetime:
    return datetime.fromtimestamp(math.floor(moment.timestamp() / step) * step, tz=UTC)


def assert_can_read_logs(team: Team, user: User, user_access_control: UserAccessControl) -> None:
    """The batch calls this once, before any LogQL target runs, with the rules it loaded to plan the other
    panels, so access rules load once per batch."""
    if not user_can_access_resource(team, user, "logs", "viewer", user_access_control=user_access_control):
        raise UserAccessControlError("logs", "viewer")
    # LogQL runs through Snuffle, which has its own private-alpha flag, as the Loki API does.
    if not posthog_feature_flag_enabled(
        SNUFFLE_API_FEATURE_FLAG, str(user.distinct_id), organization_id=team.organization_id, team_id=team.pk
    ):
        raise UserAccessControlError("logs", "viewer")


async def _read_capped(response: httpx.Response) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
        body.extend(chunk)
        if len(body) > MAX_LOGQL_RESPONSE_BYTES:
            raise TelemetryTargetError(
                "The LogQL query returned too much data. Aggregate by fewer labels or shorten the range."
            )
    return bytes(body)


def _upstream_error(body: Any) -> str:
    message = body.get("error") if isinstance(body, dict) else None
    return str(message) if message else "The LogQL query failed."


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return None


def logql_budget(team: Team) -> Optional[BudgetSpec]:
    """The read-byte budget that LogQL targets are held to, or None when it is not enforced. The batch reads it
    once, because the spec costs a Postgres read, and each target then reads only its balance."""
    if not budget_enabled() or not api_queries_budget_enforcement_enabled(team):
        return None
    try:
        return budget_spec_for(team.organization, events_last_year_for(team.pk))
    except Exception as e:
        # The budget fails open, as it does for the Loki API.
        capture_exception(e)
        return None


def _assert_budget_left(team: Team, budget: Optional[BudgetSpec]) -> None:
    """The Loki API refuses a read once the read-byte budget is spent, so a LogQL panel does too."""
    if budget is None:
        return
    remaining = refill_and_read(str(team.pk), budget)
    if remaining is not None and remaining <= 0:
        raise TelemetryTargetError("This project has used its query budget for now. Try again later.")


def _query_range(team: Team, data: dict[str, str], budget: Optional[BudgetSpec], cancelled: Optional[Event]) -> Any:
    """The body is read inside the telemetry slot, so a slow or large response keeps holding it."""
    _assert_budget_left(team, budget)
    with get_app_telemetry_queries_rate_limiter().run(org_id=team.organization_id, team_id=team.pk, is_api=False):
        try:
            return asyncio.run(_query_range_async(team.pk, data, cancelled))
        except SnuffleNotConfiguredError as exc:
            raise TelemetryTargetError("LogQL queries are not available on this PostHog instance.") from exc
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise TelemetryTargetError("The LogQL query timed out. Try a shorter date range.") from exc
        except httpx.RequestError as exc:
            raise TelemetryTargetError("The LogQL query backend cannot be reached. Try again later.") from exc


async def _query_range_async(team_id: int, data: dict[str, str], cancelled: Optional[Event]) -> Any:
    if cancelled is not None and cancelled.is_set():
        raise asyncio.CancelledError

    async def request() -> Any:
        async with snuffle_stream(team_id, "POST", "/loki/api/v1/query_range", data=data) as response:
            return await _loki_data(response)

    async def wait_for_disconnect() -> None:
        assert cancelled is not None
        while not cancelled.is_set():
            await asyncio.sleep(0.1)

    request_task = asyncio.create_task(request())
    monitor = asyncio.create_task(wait_for_disconnect()) if cancelled is not None else None
    tasks = {request_task}
    if monitor is not None:
        tasks.add(monitor)
    try:
        done, _ = await asyncio.wait(
            tasks, timeout=settings.SNUFFLE_APM_TIMEOUT_SECONDS, return_when=asyncio.FIRST_COMPLETED
        )
        if request_task in done:
            return request_task.result()
        if monitor is not None and monitor in done:
            raise asyncio.CancelledError
        raise TimeoutError
    finally:
        # Only this supervisor cancels the HTTP task, so a disconnect cannot interrupt timeout cleanup.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _loki_data(response: httpx.Response) -> Any:
    if response.status_code in (401, 403) or response.status_code >= 500:
        logger.error("dashboard_v2_logql_upstream_failed", status_code=response.status_code)
        raise TelemetryTargetError("The LogQL query backend failed. Try again later.")
    payload = _decode(await _read_capped(response))
    if response.status_code >= 400:
        raise TelemetryTargetError(_upstream_error(payload))
    if payload is None:
        raise TelemetryTargetError("The LogQL query backend sent a response that cannot be read.")
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise TelemetryTargetError(_upstream_error(payload))
    return payload.get("data")


def run_logql(
    *,
    team: Team,
    logql: str,
    date_from: str,
    date_to: str,
    min_interval: Optional[str],
    max_data_points: Optional[int],
    budget: Optional[BudgetSpec] = None,
    cancelled: Optional[Event] = None,
) -> dict[str, Any]:
    """Run a LogQL range query on Snuffle, uncached. Returns Loki's `data` as `results`. The caller has
    checked logs access with `assert_can_read_logs`."""
    if not logql.strip():
        raise TelemetryTargetError("Write a LogQL query first.")
    window = time_range(date_from, date_to, tz=team.timezone_info)
    start, end = window.start, window.end
    step = pick_step(end - start, max_data_points=max_data_points, min_interval=min_interval, is_promql=False).seconds
    if not returns_log_lines(logql):
        # Series are evaluated at multiples of the step, so every refresh lands on the same timestamps.
        start, end = _align(start, step), _align(end, step)
    data = {
        "query": logql,
        "start": str(start.timestamp()),
        "end": str(end.timestamp()),
        "step": str(step),
        "limit": str(LOG_LINE_LIMIT),
    }
    results = _query_range(team, data, budget, cancelled)
    return {
        "results": results,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step": step,
        "last_refresh": now().isoformat(),
        "cache_key": None,
    }
