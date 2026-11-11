"""The state of a platform alert over a recent window, as the alert lists draw it.

Built from the platform's check history and its control-plane changes alone. The logs alert list
draws the same bar from its own rows; this is that bar for an alert with no source row.

A grouped alert has one state per group. The bar shows the most urgent of them, as the list's
status does, and a whole-alert snooze shows over all of them.
"""

from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from typing import Final

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import (
    ControlChangeKind,
    PlatformAlertHistory,
    PlatformControlHistory,
    StateInterval,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertState

_TOGGLES: Final = {ControlChangeKind.ENABLE: True, ControlChangeKind.DISABLE: False}
_SNOOZES: Final = {ControlChangeKind.SNOOZE: True, ControlChangeKind.UNSNOOZE: False}

# Most urgent first, matching how the list picks one status for a grouped alert.
_PRIORITY: Final = (
    PlatformAlertState.BROKEN,
    PlatformAlertState.ERRORED,
    PlatformAlertState.FIRING,
    PlatformAlertState.NOT_FIRING,
)


@frozen
class _Move:
    at: datetime
    # Set for a check: the group it moved and the state it moved to.
    grouping_key: str | None = None
    state: PlatformAlertState | None = None
    enabled: bool | None = None
    snoozed: bool | None = None
    reset: bool = False


# A check that failed before any group was known is recorded against the whole configuration.
_CONFIGURATION_KEY: Final = ""
_FAILED: Final = frozenset({PlatformAlertState.ERRORED, PlatformAlertState.BROKEN})


class _GroupStates:
    """Each group's state, with a count per state so the whole alert's state costs nothing to read
    however many groups an alert has churned through."""

    def __init__(self, states: Mapping[str, PlatformAlertState]) -> None:
        self._states: dict[str, PlatformAlertState] = {}
        self._counts: Counter[PlatformAlertState] = Counter()
        for key, state in states.items():
            self.set(key, state)

    def set(self, key: str, state: PlatformAlertState) -> None:
        previous = self._states.get(key)
        if previous is not None:
            self._counts[previous] -= 1
        self._states[key] = state
        self._counts[state] += 1

    def group_moved(self, key: str, state: PlatformAlertState) -> None:
        self.set(key, state)
        # A group's check ran, so a failure recorded against the whole configuration is over.
        if key != _CONFIGURATION_KEY and self._states.get(_CONFIGURATION_KEY) in _FAILED:
            self._counts[self._states.pop(_CONFIGURATION_KEY)] -= 1

    def reset(self) -> None:
        for key in [key for key, state in self._states.items() if state == PlatformAlertState.BROKEN]:
            self.set(key, PlatformAlertState.NOT_FIRING)

    def whole(self, snoozed: bool) -> PlatformAlertState:
        if snoozed:
            return PlatformAlertState.SNOOZED
        return next((state for state in _PRIORITY if self._counts[state] > 0), PlatformAlertState.NOT_FIRING)


def state_timeline(
    *,
    history: PlatformAlertHistory | None,
    control: PlatformControlHistory | None,
    current_group_states: Mapping[str, PlatformAlertState],
    current_enabled: bool,
    snooze_until: datetime | None,
    window: tuple[datetime, datetime],
) -> tuple[StateInterval, ...]:
    """Intervals over `window`, oldest first, each with one (state, enabled) pair. Neighbours differ."""
    window_start, window_end = window
    state_changes = history.state_changes if history else ()
    control_changes = control.changes if control else ()
    moves = [
        _Move(at=change.occurred_at, grouping_key=change.grouping_key, state=change.state) for change in state_changes
    ]
    moves.extend(
        _Move(
            at=change.occurred_at,
            enabled=_TOGGLES.get(change.kind),
            snoozed=_SNOOZES.get(change.kind),
            reset=change.kind == ControlChangeKind.RESET,
        )
        for change in control_changes
    )
    # A check that fails is recorded against the whole configuration, but the groups' checks that
    # follow it write no row while their states hold. When the alert is not failing now, the failure
    # was over by its last check, which is the latest time the history can show it ending.
    configuration_failures = [
        change for change in state_changes if change.grouping_key == _CONFIGURATION_KEY and change.state in _FAILED
    ]
    if (
        history is not None
        and configuration_failures
        and current_group_states.get(_CONFIGURATION_KEY) not in _FAILED
        and window_start < history.last_checked_at < window_end
        and history.last_checked_at > configuration_failures[-1].occurred_at
    ):
        moves.append(
            _Move(at=history.last_checked_at, grouping_key=_CONFIGURATION_KEY, state=PlatformAlertState.NOT_FIRING)
        )
    # A snooze that ran out leaves no row, so only the current one can end inside the window.
    snooze_events = [move for move in moves if move.snoozed is not None]
    if snooze_until is not None and window_start < snooze_until < window_end:
        if not any(move.at >= snooze_until for move in snooze_events):
            moves.append(_Move(at=snooze_until, snoozed=False))
    moves.sort(key=lambda move: move.at)

    # Each group starts in the state its first in-window change moved it from, else the state it holds now.
    seed: dict[str, PlatformAlertState] = dict(current_group_states)
    for change in reversed(state_changes):
        seed[change.grouping_key] = change.previous_state
    # A control change records the whole alert's state before it. When one comes before any check moved,
    # it says how the window began, which a reset of an alert broken before the window needs.
    first_control = control_changes[0] if control_changes else None
    first_check_at = state_changes[0].occurred_at if state_changes else None
    if (
        first_control is not None
        and first_control.previous_state in _FAILED
        and (first_check_at is None or first_control.occurred_at < first_check_at)
    ):
        seed[_CONFIGURATION_KEY] = first_control.previous_state
    group_states = _GroupStates(seed)
    first_snooze = next((move for move in moves if move.snoozed is not None), None)
    snoozed = (
        not first_snooze.snoozed
        if first_snooze is not None
        else snooze_until is not None and snooze_until > window_start
    )
    enabled = _enabled_at_start(control, moves, current_enabled)

    intervals: list[StateInterval] = []
    start, shown = window_start, group_states.whole(snoozed)
    for move in moves:
        if move.state is not None and move.grouping_key is not None:
            group_states.group_moved(move.grouping_key, move.state)
        if move.reset:
            group_states.reset()
        if move.snoozed is not None:
            snoozed = move.snoozed
        next_enabled = enabled if move.enabled is None else move.enabled
        next_shown = group_states.whole(snoozed)
        if next_shown == shown and next_enabled == enabled:
            continue
        intervals.append(StateInterval(start=start, end=move.at, state=shown, enabled=enabled))
        start, shown, enabled = move.at, next_shown, next_enabled
    intervals.append(StateInterval(start=start, end=window_end, state=shown, enabled=enabled))
    return tuple(intervals)


def _enabled_at_start(control: PlatformControlHistory | None, moves: list[_Move], current_enabled: bool) -> bool:
    if control is not None and control.toggle_before is not None:
        return _TOGGLES[control.toggle_before]
    first_toggle = next((move for move in moves if move.enabled is not None), None)
    # Before a toggle, the alert was in the opposite position to the one the toggle set.
    return not first_toggle.enabled if first_toggle is not None else current_enabled
