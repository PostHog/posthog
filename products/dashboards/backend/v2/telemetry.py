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
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any, Optional

from django.utils.timezone import now

import requests
from dateutil.relativedelta import relativedelta

from posthog.api.snuffle_proxy import SNUFFLE_API_FEATURE_FLAG, SnuffleNotConfiguredError, snuffle_request
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.limit import get_app_telemetry_queries_rate_limiter
from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError

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
# Double-quoted strings with escapes, and raw backtick strings, as LogQL writes them.
_LOGQL_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|`[^`]*`')


class TelemetryTargetError(ValueError):
    """A PromQL or LogQL target that cannot run. The message is safe to show."""


def _parse_time(expression: str, at: datetime, tz: tzinfo) -> datetime:
    """Months and years are calendar months and years, and an ISO date without an offset is in the project's
    timezone, as `MetricsQuery` reads them, so a PromQL and a LogQL panel with one range read the same window."""
    if expression == "now":
        return at
    try:
        if match := _RELATIVE.fullmatch(expression):
            amount, unit = int(match.group(1)), match.group(2)
            if unit == "M":
                return at - relativedelta(months=amount)
            if unit == "y":
                return at - relativedelta(years=amount)
            return at - timedelta(seconds=amount * _UNIT_SECONDS[unit])
        parsed = datetime.fromisoformat(expression)
    except (ValueError, OverflowError):
        raise TelemetryTargetError(f"Unsupported time expression: {expression!r}.")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


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
    at = (at or now()).astimezone(tz)
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


def returns_log_lines(logql: str) -> bool:
    return bool(logql.strip()) and _METRIC_LOGQL.search(_LOGQL_STRING.sub('""', logql)) is None


def _align(moment: datetime, step: int) -> datetime:
    return datetime.fromtimestamp(math.floor(moment.timestamp() / step) * step, tz=UTC)


def assert_can_read_logs(team: Team, user: User, user_access_control: UserAccessControl) -> None:
    """The batch calls this once, before any LogQL target runs, so access rules load once per batch."""
    user_access_control.assert_access_level_for_resource("logs", "viewer")
    # LogQL runs through Snuffle, which has its own private-alpha flag, as the Loki API does.
    if not posthog_feature_flag_enabled(
        SNUFFLE_API_FEATURE_FLAG, str(user.distinct_id), organization_id=team.organization_id, team_id=team.pk
    ):
        raise UserAccessControlError("logs", "viewer")


def _read_capped(response: requests.Response) -> bytes:
    body = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_LOGQL_RESPONSE_BYTES:
                raise TelemetryTargetError(
                    "The LogQL query returned too much data. Aggregate by fewer labels or shorten the range."
                )
    except requests.RequestException as exc:
        raise TelemetryTargetError("The LogQL query backend cannot be reached. Try again later.") from exc
    finally:
        response.close()
    return bytes(body)


def _upstream_error(body: Any) -> str:
    message = body.get("error") if isinstance(body, dict) else None
    return str(message) if message else "The LogQL query failed."


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _query_range(team: Team, data: dict[str, str]) -> requests.Response:
    with get_app_telemetry_queries_rate_limiter().run(org_id=team.organization_id, team_id=team.pk, is_api=False):
        try:
            return snuffle_request(
                team.pk, "POST", "/loki/api/v1/query_range", data=data, workload=Workload.LOGS, stream=True
            )
        except SnuffleNotConfiguredError as exc:
            raise TelemetryTargetError("LogQL queries are not available on this PostHog instance.") from exc
        except requests.Timeout as exc:
            raise TelemetryTargetError("The LogQL query timed out. Try a shorter date range.") from exc
        except requests.RequestException as exc:
            raise TelemetryTargetError("The LogQL query backend cannot be reached. Try again later.") from exc


def _loki_data(response: requests.Response) -> Any:
    if response.status_code in (401, 403) or response.status_code >= 500:
        response.close()
        raise TelemetryTargetError("The LogQL query backend failed. Try again later.")
    payload = _decode(_read_capped(response))
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
    results = _loki_data(_query_range(team, data))
    return {
        "results": results,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step": step,
        "last_refresh": now().isoformat(),
        "cache_key": None,
    }
