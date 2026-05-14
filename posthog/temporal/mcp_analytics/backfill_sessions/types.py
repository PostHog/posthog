from dataclasses import dataclass


@dataclass(frozen=True)
class BackfillMCPSessionsInput:
    # How far back to look for mcp_tool_call events on each run. Sessions whose
    # last_seen falls within this window get (re)aggregated and upserted.
    lookback_hours: int = 24
