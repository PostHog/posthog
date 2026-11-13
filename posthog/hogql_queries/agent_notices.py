from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypedDict


class AgentNotice(TypedDict):
    source: str
    key: str
    text: str


_collected: ContextVar[list[AgentNotice] | None] = ContextVar("agent_notices", default=None)


@contextmanager
def collect_agent_notices() -> Iterator[list[AgentNotice]]:
    notices: list[AgentNotice] = []
    token = _collected.set(notices)
    try:
        yield notices
    finally:
        _collected.reset(token)


@contextmanager
def claim_agent_notices() -> Iterator[list[AgentNotice] | None]:
    """Collects notices unless an outer caller already does, in which case they go to that caller."""
    if _collected.get() is not None:
        yield None
        return
    with collect_agent_notices() as notices:
        yield notices


def is_collecting_agent_notices() -> bool:
    return _collected.get() is not None


def hand_off_agent_notices(notices: Sequence[AgentNotice]) -> None:
    collected = _collected.get()
    if collected is None:
        return
    seen = {(notice["source"], notice["key"]) for notice in collected}
    collected.extend(notice for notice in notices if (notice["source"], notice["key"]) not in seen)
