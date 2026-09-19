"""Agent tools for the anomaly investigation workflow.

Each tool is a narrow, read-only wrapper around existing PostHog query machinery.
All tools are bound to a team and enforce team isolation via the Team instance
they hold — they do NOT accept arbitrary team IDs from the LLM.

Tools return compact strings suitable for inclusion in the LLM's context. A
failed query comes back as an instruction to act on, because the agent otherwise
reads any failure as proof that the data itself cannot be read. A rejected
statement says to fix and retry. A timeout or a capacity error says the engine
failed, so that the agent does not rewrite valid SQL.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field

from posthog.hogql.query import execute_hogql_query

from posthog.errors import QueryErrorCategory, classify_query_error
from posthog.models import Team

from products.alerts.backend.models.alert import AlertConfiguration

logger = structlog.get_logger(__name__)

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

# Said on a rejected query. The agent reads a raw engine error as "this data is not
# available to me" and writes that into the report, which sends the reader to inspect the
# pipeline behind a table that is serving rows.
_QUERY_REJECTED_HELP = (
    "The query was rejected before it ran. This says nothing about whether the table, view or "
    "event stream exists — it is a defect in the query text. Rewrite the query and run it again. "
    "Do not report a data source as unreadable, missing or unreachable because a query failed."
)

# Said when the engine failed the query instead of rejecting it. The statement is valid, so a
# rewrite spends one of ten tool calls and changes nothing.
_QUERY_UNAVAILABLE_HELP = (
    "This is a failure in the engine that ran the query, not a defect in the query text. The "
    "same query can succeed on a later attempt. Do not rewrite it, and do not report a data "
    "source as unreadable, missing or unreachable because a query failed."
)

# Said when the query ran and hit a limit. The fix is a smaller question, not different SQL.
_QUERY_TOO_EXPENSIVE_HELP = (
    "The query reached the engine and hit a resource limit, so the query text is valid. Ask for "
    "less instead of rewriting it: a shorter window, fewer groups, or a lower limit. Do not "
    "report a data source as unreadable, missing or unreachable because a query failed."
)

# Errors that a different alias name fixes. Both engines word it differently, and ClickHouse's
# cyclic-alias error names no identifier at all, so the offending alias is found in the SQL.
_ALIAS_CONFLICT_MARKERS = (
    "cyclic alias",
    "redefine an alias",
    "duplicate column alias",
    "inside another aggregate function",
)

# Only aggregates are renamed. `toStartOfHour(h) AS h` is accepted, so rewriting it would
# change a working expression while chasing an unrelated error.
_AGGREGATE_FUNCTIONS = frozenset(
    {
        "any",
        "anylast",
        "avg",
        "count",
        "max",
        "median",
        "min",
        "sum",
        "uniq",
        "uniqexact",
    }
)

_AGGREGATE_ALIAS = re.compile(
    r"\b(?P<fn>\w+)\s*\(\s*(?:\w+\.)?(?P<column>\w+)\s*\)\s+AS\s+(?P<alias>\w+)\b",
    re.IGNORECASE,
)


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


def _is_alias_conflict(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _ALIAS_CONFLICT_MARKERS)


def rename_shadowing_aliases(sql: str) -> tuple[str, dict[str, str]]:
    """Rename every aggregate that is aliased to the column it aggregates.

    ``sum(runs) AS runs`` makes the alias and its own operand the same name, which the engine
    rejects. The agent writes this shape repeatedly, then reads the rejection as the table being
    unreadable and abandons the probe. Renaming the alias keeps the query's meaning and lets the
    probe run. Returns the rewritten SQL and the old-to-new alias names.
    """
    renames: dict[str, str] = {}

    def rename(match: re.Match[str]) -> str:
        original = match.group(0)
        function, column, alias = match.group("fn"), match.group("column"), match.group("alias")
        if function.lower() not in _AGGREGATE_FUNCTIONS or alias.lower() != column.lower():
            return original
        renamed = f"{alias}_{function.lower()}"
        renames[alias] = renamed
        # Only the alias token moves. The aggregate expression is left exactly as written.
        return original[: match.start("alias") - match.start()] + renamed

    return _AGGREGATE_ALIAS.sub(rename, sql), renames


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
    from products.alerts.backend.evaluation.detector import simulate_detector_on_insight

    try:
        return simulate_detector_on_insight(
            insight=alert.insight,
            team=team,
            detector_config=alert.detector_config or {"type": "zscore", "threshold": 0.95},
            # Mirror the alert-check path (TrendsDetectorExtractor.extract): the monitored series
            # is chosen by config.series_index. Without this the simulation defaults to series 0,
            # so the investigation analyzes a different series than the one that actually fired.
            series_index=(alert.config or {}).get("series_index", 0),
            # Pass the full alert config too: HogQLDetectorExtractor.simulate reads config.column to
            # pick which numeric column to score. Without it a SQL insight with several numeric
            # columns fails with "more than one of them is numeric", so the investigation gets no
            # series and no baseline.
            config=alert.config,
            date_from=date_from,
            user=alert.created_by,
        )
    except Exception as err:
        return str(err)


def _describe_query_failure(err: Exception, message: str) -> str:
    """Name what failed, so the agent only rewrites SQL when the SQL is the problem.

    The tool returns this text instead of raising, so nothing else records the failure. Log it
    with its category here, or a query that fails during a cluster incident leaves no trace.
    """
    category = classify_query_error(err)
    logger.warning("anomaly_investigation.query_failed", category=str(category), error=message)

    if category == QueryErrorCategory.QUERY_PERFORMANCE_ERROR:
        return f"Query hit a resource limit: {message}\n{_QUERY_TOO_EXPENSIVE_HELP}"
    if category in (QueryErrorCategory.RATE_LIMITED, QueryErrorCategory.CANCELLED):
        return f"Query did not complete: {message}\n{_QUERY_UNAVAILABLE_HELP}"
    return f"Query rejected: {message}\n{_QUERY_REJECTED_HELP}"


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
        try:
            return json.dumps(await self._execute(sql), default=str)
        except Exception as err:
            failure = err
        message = str(failure)

        retried, renames = rename_shadowing_aliases(sql)
        if not renames or not _is_alias_conflict(message):
            return _describe_query_failure(failure, message)

        try:
            payload = await self._execute(retried)
        except Exception as retry_err:
            return (
                f"{_describe_query_failure(failure, message)}\n"
                "An aggregate is aliased to the column it aggregates. Renaming it "
                f"({_format_renames(renames)}) still failed: {retry_err}"
            )

        payload["renamed_aliases"] = renames
        payload["note"] = (
            "Your query aliased an aggregate to the column it aggregates, which the engine "
            f"rejects. It was re-run with {_format_renames(renames)}, so read the results under "
            "the new column names. The data was always readable."
        )
        return json.dumps(payload, default=str)

    async def _execute(self, sql: str) -> dict[str, Any]:
        response = await sync_to_async(execute_hogql_query, thread_sensitive=False)(
            query=sql,
            team=self.team,
        )
        rows = response.results or []
        return {
            "columns": response.columns or [],
            "rows": [list(row) for row in rows[:MAX_HOGQL_ROWS]],
            "row_count": len(rows),
            "truncated": len(rows) > MAX_HOGQL_ROWS,
        }

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


def _format_renames(renames: dict[str, str]) -> str:
    return ", ".join(f"{old} renamed to {new}" for old, new in renames.items())


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
