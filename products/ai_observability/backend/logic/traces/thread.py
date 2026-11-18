from collections.abc import Sequence

from .event import TraceEvent


# Same heuristic as `pickUserVisibleTurn` in the frontend and the exploring-llm-traces skill script; keep them in sync.
def pick_user_visible_generation(events: Sequence[TraceEvent]) -> TraceEvent | None:
    latest: TraceEvent | None = None
    for event in events:
        if event.kind == "generation" and (latest is None or event.row.timestamp > latest.row.timestamp):
            latest = event
    return latest
