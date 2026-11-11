"""The state of a platform alert over a recent window, as the alert lists draw it.

Built from the platform's check history and its control-plane changes alone. The logs alert list
draws the same bar from its own rows; this is that bar for an alert with no source row.
"""

from datetime import datetime

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import (
    ControlChangeKind,
    PlatformAlertHistory,
    PlatformControlHistory,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertState

_TOGGLES = {ControlChangeKind.ENABLE: True, ControlChangeKind.DISABLE: False}


@frozen
class StateInterval:
    start: datetime
    end: datetime
    state: PlatformAlertState
    enabled: bool


@frozen
class _Move:
    at: datetime
    previous_state: PlatformAlertState
    state: PlatformAlertState
    enabled: bool | None


def state_timeline(
    *,
    history: PlatformAlertHistory | None,
    control: PlatformControlHistory | None,
    current_state: PlatformAlertState,
    current_enabled: bool,
    window: tuple[datetime, datetime],
) -> tuple[StateInterval, ...]:
    """Intervals over `window`, oldest first, each with one (state, enabled) pair. Neighbours differ."""
    window_start, window_end = window
    moves = sorted(
        [
            *(
                _Move(at=change.occurred_at, previous_state=change.previous_state, state=change.state, enabled=None)
                for change in (history.state_changes if history else ())
            ),
            *(
                _Move(
                    at=change.occurred_at,
                    previous_state=change.previous_state,
                    state=change.state,
                    enabled=_TOGGLES.get(change.kind),
                )
                for change in (control.changes if control else ())
            ),
        ],
        key=lambda move: move.at,
    )
    state = moves[0].previous_state if moves else current_state
    enabled = _enabled_at_start(control, moves, current_enabled)

    intervals: list[StateInterval] = []
    start = window_start
    for move in moves:
        next_enabled = enabled if move.enabled is None else move.enabled
        if move.state == state and next_enabled == enabled:
            continue
        intervals.append(StateInterval(start=start, end=move.at, state=state, enabled=enabled))
        start, state, enabled = move.at, move.state, next_enabled
    intervals.append(StateInterval(start=start, end=window_end, state=state, enabled=enabled))
    return tuple(intervals)


def _enabled_at_start(control: PlatformControlHistory | None, moves: list[_Move], current_enabled: bool) -> bool:
    if control is not None and control.toggle_before is not None:
        return _TOGGLES[control.toggle_before]
    first_toggle = next((move for move in moves if move.enabled is not None), None)
    # Before a toggle, the alert was in the opposite position to the one the toggle set.
    return not first_toggle.enabled if first_toggle is not None else current_enabled
