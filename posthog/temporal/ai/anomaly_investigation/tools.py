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

MAX_HOGQL_ROWS = 50

_DATE_HELP = (
    "Accepts PostHog relative shorthands ('-7d', '-24h', 'now') — resolved to an "
    "absolute ISO timestamp server-side before the query runs. Absolute dates "
    "('2024-04-01', '2024-04-01 12:00:00') also work."
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


@dataclass
class InvestigationToolkit:
    """Bundles the tool implementations bound to a team. Returned strings are designed
    to be compact — rough cap ~2KB per response to keep LLM context lean."""

    team: Team

    async def run_hogql_query(self, args: RunHogQLQueryArgs) -> str:
        sql = args.query.strip()
        if not sql.lower().lstrip("(").startswith("select"):
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
                    f"AND timestamp <= {_escape_literal(_resolve_date(args.date_to))} "
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
            f"AND timestamp <= {_escape_literal(_resolve_date(args.date_to))} "
            f"{event_filter}"
            f"ORDER BY timestamp DESC LIMIT {int(args.limit)}"
        )
        return await self.run_hogql_query(RunHogQLQueryArgs(query=query))


def _escape_literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


_RELATIVE_DATE = re.compile(r"^-(\d+)([smhdw])$")
_DATE_UNIT_TO_DELTA = {
    "s": lambda n: timedelta(seconds=n),
    "m": lambda n: timedelta(minutes=n),
    "h": lambda n: timedelta(hours=n),
    "d": lambda n: timedelta(days=n),
    "w": lambda n: timedelta(weeks=n),
}


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
