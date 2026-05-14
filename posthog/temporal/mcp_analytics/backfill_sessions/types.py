from dataclasses import dataclass


@dataclass(frozen=True)
class BackfillMCPSessionsInput:
    # How far back to look for *active* mcp_tool_call events on each run. Sessions
    # that received any event in this window get re-aggregated from their full
    # history, so this only needs to span the longest plausible "still-mutating"
    # gap between events on a live session.
    lookback_hours: int = 1
