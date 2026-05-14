"""Toolkit for the followup agent that runs inside analyze_live_investigation_activity.

Three tools:
- get_event_detail: drill into one event the agent wants to inspect
- run_hogql_query: cross-check probe data against other PostHog data
- start_live_investigation: chain a child investigation

By design, NO install/uninstall tool — program lifecycle is the workflow's job, not
the agent's. To get more data, chain a new investigation; the current one will be
cleaned up regardless.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field

from posthog.hogql.query import execute_hogql_query
from posthog.models import Team
from posthog.temporal.ai.live_investigation.schemas import StartLiveInvestigationArgs

from products.live_debugger.backend.facade.api import start_live_investigation as start_live_investigation_facade
from products.live_debugger.backend.models import LiveInvestigation, ProgramEvent

MAX_HOGQL_ROWS = 50


class GetEventDetailArgs(BaseModel):
    event_id: str = Field(description="UUID of the probe event to inspect in full detail.")


class RunHogQLQueryArgs(BaseModel):
    query: str = Field(description="A HogQL SELECT statement. Results are capped at a few dozen rows.")


@dataclass
class LiveInvestigationToolkit:
    """Bundles the followup agent's tools, bound to a team and investigation.

    `events` is pre-loaded so the agent already has the aggregated view in its
    context window before any tool call. Tools are reserved for drill-down,
    cross-checks, and chaining decisions.
    """

    team: Team
    investigation: LiveInvestigation
    events: list[ProgramEvent] = field(default_factory=list)
    heartbeat: Callable[[], None] | None = None

    async def get_event_detail(self, args: GetEventDetailArgs) -> str:
        for evt in self.events:
            if evt.id == args.event_id:
                return json.dumps(evt.to_json(), default=str)
        return json.dumps({"error": f"event_id {args.event_id} not in loaded sample"})

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

    async def start_live_investigation(self, args: StartLiveInvestigationArgs) -> str:
        # Force the parent_investigation_id to the current investigation so the
        # agent can't accidentally orphan a chain.
        args = args.model_copy(update={"parent_investigation_id": self.investigation.id})
        investigation_id = await start_live_investigation_facade(
            team=self.team,
            signal_source_type=self.investigation.signal_source_type,
            signal_source_id=self.investigation.signal_source_id,
            args=args,
        )
        return json.dumps({"investigation_id": investigation_id, "parent_id": str(self.investigation.id)})
