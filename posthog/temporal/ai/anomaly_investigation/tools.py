"""Agent tools for the anomaly investigation workflow.

Each tool is a narrow, read-only wrapper around existing PostHog query machinery.
All tools are bound to a team and enforce team isolation via the Team instance
they hold — they do NOT accept arbitrary team IDs from the LLM.

Tools return compact strings suitable for inclusion in the LLM's context. They
raise on error so the agent loop can catch and feed the error message back.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field

from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.models.alert import AlertConfiguration

MAX_HOGQL_ROWS = 50
MAX_SERIES_POINTS = 120

_DATE_HELP = (
    "Accepts PostHog relative shorthands ('-7d', '-24h', 'now') — resolved to an "
    "absolute ISO timestamp server-side before the query runs. Absolute dates "
    "('2024-04-01', '2024-04-01 12:00:00') also work."
)

_RELATIVE_DATE = re.compile(r"^-(\d+)([smhdw])$")
_DATE_UNIT_TO_DELTA = {
    "s": lambda n: timedelta(seconds=n),
    "m": lambda n: timedelta(minutes=n),
    "h": lambda n: timedelta(hours=n),
    "d": lambda n: timedelta(days=n),
    "w": lambda n: timedelta(weeks=n),
}
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class RunHogQLQueryArgs(BaseModel):
    query: str = Field(description="A HogQL SELECT statement. Results are limited to a few dozen rows.")


class TopBreakdownArgs(BaseModel):
    event: str = Field(description="Event name, e.g. '$pageview' or 'purchase'.")
    property: str = Field(description="Property key to group by, e.g. '$browser' or 'plan'.")
    date_from: str = Field(description=f"Start of the window. {_DATE_HELP}")
    date_to: str = Field(description=f"End of the window. {_DATE_HELP}")
    limit: int = Field(default=10, description="Max breakdown values to return.", ge=1, le=25)


class RecentEventsArgs(BaseModel):
    event: str | None = Field(default=None, description="Optional event name filter. Null returns any event.")
    date_from: str = Field(description=f"Start of the window. {_DATE_HELP}")
    date_to: str = Field(description=f"End of the window. {_DATE_HELP}")
    limit: int = Field(default=10, description="Max events to return.", ge=1, le=25)


class FetchMetricSeriesArgs(BaseModel):
    date_from: str | None = Field(
        default=None,
        description=(
            "Optional override for the series start. Accepts PostHog relative shorthands "
            "('-30d', '-14d') or an ISO date. If omitted, uses the insight's configured range."
        ),
    )


class SimulateDetectorArgs(BaseModel):
    date_from: str | None = Field(
        default=None,
        description=(
            "Optional window override ('-30d', '-90d', or ISO). The detector needs a minimum "
            "number of samples — the helper extends this window automatically if needed."
        ),
    )


def _compact(seq: list[Any]) -> list[Any]:
    """Tail-truncate long series so the LLM can still see the anomaly without flooding
    its context. Keeps the last MAX_SERIES_POINTS points — that's where the fire lives.
    """
    if len(seq) <= MAX_SERIES_POINTS:
        return list(seq)
    return list(seq[-MAX_SERIES_POINTS:])


def _run_detector_simulation(
    *,
    alert: AlertConfiguration,
    team: Team,
    date_from: str | None,
) -> dict[str, Any] | str:
    """Thin wrapper around ``simulate_detector_on_insight`` that returns either the sim
    dict or a short error string. Kept as a sync helper so it can be pushed to a thread
    via ``sync_to_async`` from the async tool handlers.
    """
    # Imported lazily because the workflow module can't pull in heavy query machinery
    # at Temporal workflow-definition time — only activities can.
    from posthog.tasks.alerts.detector import simulate_detector_on_insight

    try:
        return simulate_detector_on_insight(
            insight=alert.insight,
            team=team,
            detector_config=alert.detector_config or {"type": "zscore", "threshold": 0.95},
            date_from=date_from,
        )
    except Exception as err:
        return str(err)


@dataclass
class InvestigationToolkit:
    """Bundles the tool implementations bound to a team and alert. Returned strings are
    compact — rough cap ~2KB per response to keep LLM context lean."""

    team: Team
    alert: AlertConfiguration | None = None

    async def run_hogql_query(self, args: RunHogQLQueryArgs) -> str:
        sql = args.query.strip()
        if not re.match(r"^\(?\s*(select|with)\b", sql, re.IGNORECASE):
            raise ValueError("Only SELECT statements are allowed.")
        response = await sync_to_async(execute_hogql_query, thread_sensitive=False)(
            query=sql,
            team=self.team,
        )
        rows = response.results or []
        truncated = rows[:MAX_HOGQL_ROWS]
        payload: dict[str, Any] = {
            "columns": response.columns or [],
            "rows": [list(row) for row in truncated],
            "row_count": len(rows),
            "truncated": len(rows) > MAX_HOGQL_ROWS,
        }
        return json.dumps(payload, default=str)

    async def top_breakdowns(self, args: TopBreakdownArgs) -> str:
        # Use bracket-notation property access so keys like '$browser' and
        # 'utm-source' survive as-is instead of being stripped by identifier
        # escaping.
        return await self.run_hogql_query(
            RunHogQLQueryArgs(
                query=(
                    f"SELECT properties[{_escape_literal(args.property)}] AS breakdown, "
                    "count() AS c FROM events "
                    f"WHERE event = {_escape_literal(args.event)} "
                    f"AND timestamp >= {_escape_literal(_resolve_date(args.date_from))} "
                    f"AND timestamp <= {_escape_literal(_resolve_date_end(args.date_to))} "
                    f"GROUP BY breakdown ORDER BY c DESC LIMIT {int(args.limit)}"
                )
            )
        )

    async def recent_events(self, args: RecentEventsArgs) -> str:
        event_filter = f"AND event = {_escape_literal(args.event)} " if args.event else ""
        query = (
            "SELECT timestamp, event, distinct_id, properties "
            "FROM events "
            f"WHERE timestamp >= {_escape_literal(_resolve_date(args.date_from))} "
            f"AND timestamp <= {_escape_literal(_resolve_date_end(args.date_to))} "
            f"{event_filter}"
            f"ORDER BY timestamp DESC LIMIT {int(args.limit)}"
        )
        return await self.run_hogql_query(RunHogQLQueryArgs(query=query))

    async def fetch_metric_series(self, args: FetchMetricSeriesArgs) -> str:
        """Return the alert's insight time series (labels + values) over a window."""
        if self.alert is None or self.alert.insight_id is None:
            return "Error: no insight bound to this investigation."

        sim = await sync_to_async(_run_detector_simulation, thread_sensitive=False)(
            alert=self.alert,
            team=self.team,
            date_from=args.date_from,
        )
        if isinstance(sim, str):
            return f"Error fetching series: {sim}"

        dates = sim.get("dates") or []
        values = sim.get("data") or []
        payload = {
            "interval": sim.get("interval"),
            "labels": _compact(dates),
            "values": _compact(values),
            "point_count": len(values),
        }
        return json.dumps(payload, default=str)

    async def simulate_detector(self, args: SimulateDetectorArgs) -> str:
        """Run the alert's detector over a historical window and return scored points."""
        if self.alert is None or self.alert.insight_id is None:
            return "Error: no insight bound to this investigation."
        if not self.alert.detector_config:
            return "Error: alert has no detector_config; simulation requires anomaly-detection mode."

        sim = await sync_to_async(_run_detector_simulation, thread_sensitive=False)(
            alert=self.alert,
            team=self.team,
            date_from=args.date_from,
        )
        if isinstance(sim, str):
            return f"Error running simulation: {sim}"

        scores = sim.get("scores") or []
        values = sim.get("data") or []
        dates = sim.get("dates") or []
        payload = {
            "interval": sim.get("interval"),
            "labels": _compact(dates),
            "values": _compact(values),
            "scores": _compact(scores),
            "triggered_dates": sim.get("triggered_dates") or [],
            "anomaly_count": sim.get("anomaly_count") or 0,
            "total_points": sim.get("total_points") or len(values),
        }
        return json.dumps(payload, default=str)


def _escape_literal(value: str) -> str:
    # Backslashes must be escaped first (before quote-doubling) so that a value
    # like \' doesn't survive as an escape sequence in HogQL's ANTLR lexer.
    escaped = value.replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"


def _resolve_date(value: str) -> str:
    """Turn PostHog-style relative shorthands ('-7d', 'now') into ISO datetimes.

    ClickHouse/HogQL can't implicit-cast '-7d' to a DateTime, so the agent's
    preferred date syntax has to be resolved in Python before being embedded as
    a string literal. Absolute strings pass through untouched.
    """
    v = (value or "").strip().lower()
    if v in ("now", ""):
        return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    m = _RELATIVE_DATE.match(v)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return (datetime.now(UTC) - _DATE_UNIT_TO_DELTA[unit](n)).strftime("%Y-%m-%d %H:%M:%S")
    return value


def _resolve_date_end(value: str) -> str:
    """Like _resolve_date but expands bare YYYY-MM-DD to end of that day.

    Alert triggered_dates are date-only strings. Using them as-is in
    ``timestamp <= 'YYYY-MM-DD'`` compares against midnight (start of that day),
    silently dropping all events that occurred during it.
    """
    resolved = _resolve_date(value)
    if _DATE_ONLY.match(resolved):
        return resolved + " 23:59:59"
    return resolved
