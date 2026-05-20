"""Deployment status state machine.

Pure Python — no Django imports — so the state machine can be exercised
in isolation. The model's TextChoices are mirrored here as a plain
StrEnum so callers outside the Django model layer (Temporal activities,
the build runner) can import this module without pulling in Django.
"""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    QUEUED = "queued"
    INITIALIZING = "initializing"
    BUILDING = "building"
    READY = "ready"
    ERROR = "error"
    CANCELLED = "cancelled"


NON_TERMINAL_STATUSES: frozenset[Status] = frozenset({Status.QUEUED, Status.INITIALIZING, Status.BUILDING})
TERMINAL_STATUSES: frozenset[Status] = frozenset({Status.READY, Status.ERROR, Status.CANCELLED})


VALID_TRANSITIONS: frozenset[tuple[Status, Status]] = frozenset(
    {
        (Status.QUEUED, Status.INITIALIZING),
        (Status.QUEUED, Status.ERROR),
        (Status.QUEUED, Status.CANCELLED),
        (Status.INITIALIZING, Status.BUILDING),
        (Status.INITIALIZING, Status.ERROR),
        (Status.INITIALIZING, Status.CANCELLED),
        (Status.BUILDING, Status.READY),
        (Status.BUILDING, Status.ERROR),
        (Status.BUILDING, Status.CANCELLED),
    }
)


class InvalidStatusTransition(Exception):
    def __init__(self, current: Status, target: Status) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current} to {target}")


def assert_valid(current: Status, target: Status) -> None:
    if (current, target) not in VALID_TRANSITIONS:
        raise InvalidStatusTransition(current, target)


def is_idempotent_noop(current: Status, target: Status) -> bool:
    """Return True when the row is already in a terminal state matching the target.

    A duplicate `ready` (or `error`/`cancelled`) callback from a racing build
    activity is safe to no-op against. Used by the transitions handler to
    distinguish "actually invalid transition" from "duplicate callback".
    """
    return current == target and current in TERMINAL_STATUSES
