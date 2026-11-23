from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from ...facade.contracts import TraceNodeKind


class _Timed(Protocol):
    @property
    def timestamp(self) -> datetime: ...


class TimedStep(Protocol):
    @property
    def kind(self) -> TraceNodeKind: ...

    @property
    def row(self) -> _Timed: ...


# Same heuristic as `pickUserVisibleTurn` in the frontend and the exploring-llm-traces skill script; keep them in sync.
def pick_user_visible_generation[S: TimedStep](events: Sequence[S]) -> S | None:
    latest: S | None = None
    for event in events:
        if event.kind == "generation" and (latest is None or event.row.timestamp > latest.row.timestamp):
            latest = event
    return latest


def pick_first_generation[S: TimedStep](events: Sequence[S]) -> S | None:
    first: S | None = None
    for event in events:
        if event.kind == "generation" and (first is None or event.row.timestamp < first.row.timestamp):
            first = event
    return first
