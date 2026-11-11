from datetime import UTC, datetime, timedelta

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import (
    ControlChangeKind,
    PlatformAlertHistory,
    PlatformControlChange,
    PlatformControlHistory,
    PlatformStateChange,
    StateInterval,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.alerts_platform.backend.logic.state_timeline import state_timeline

START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(hours=24)
MID = START + timedelta(hours=10)
LATER = START + timedelta(hours=15)

OK = PlatformAlertState.NOT_FIRING
FIRING = PlatformAlertState.FIRING


def _history(
    *changes: tuple[datetime, PlatformAlertState, PlatformAlertState, str], last_checked_at: datetime = END
) -> PlatformAlertHistory:
    return PlatformAlertHistory(
        state_changes=tuple(
            PlatformStateChange(occurred_at=at, previous_state=before, state=after, grouping_key=group)
            for at, before, after, group in changes
        ),
        last_checked_at=last_checked_at,
        last_error_message=None,
    )


def _control(
    *changes: tuple[datetime, ControlChangeKind] | tuple[datetime, ControlChangeKind, PlatformAlertState],
    toggle_before: ControlChangeKind | None = None,
) -> PlatformControlHistory:
    return PlatformControlHistory(
        changes=tuple(
            PlatformControlChange(
                occurred_at=change[0],
                evaluation_key="",
                kind=change[1],
                previous_state=change[2] if len(change) > 2 else OK,
                state=OK,
            )
            for change in changes
        ),
        oldest_at=START,
        toggle_before=toggle_before,
    )


SNOOZED = PlatformAlertState.SNOOZED


@parameterized.expand(
    [
        ("no history keeps the current state", None, None, {"": FIRING}, None, [(START, END, FIRING, True)]),
        (
            "a state change splits the window and seeds from the state before it",
            _history((MID, OK, FIRING, "")),
            None,
            {"": FIRING},
            None,
            [(START, MID, OK, True), (MID, END, FIRING, True)],
        ),
        (
            "a disable splits the window and the alert was enabled before it",
            None,
            _control((MID, ControlChangeKind.DISABLE)),
            {"": OK},
            None,
            [(START, MID, OK, True), (MID, END, OK, False)],
        ),
        (
            "a toggle before the window seeds the enabled setting",
            _history((MID, OK, FIRING, "")),
            _control((LATER, ControlChangeKind.ENABLE), toggle_before=ControlChangeKind.DISABLE),
            {"": FIRING},
            None,
            [(START, MID, OK, False), (MID, LATER, FIRING, False), (LATER, END, FIRING, True)],
        ),
        (
            "a grouped alert fires while any group fires",
            _history((MID, OK, FIRING, "checkout"), (LATER, FIRING, OK, "checkout")),
            None,
            {"checkout": OK, "payments": OK},
            None,
            [(START, MID, OK, True), (MID, LATER, FIRING, True), (LATER, END, OK, True)],
        ),
        (
            "a failure recorded against the whole alert ends by the last check when it is not failing now",
            _history((MID, OK, PlatformAlertState.ERRORED, ""), last_checked_at=LATER),
            None,
            {"checkout": OK},
            None,
            [(START, MID, OK, True), (MID, LATER, PlatformAlertState.ERRORED, True), (LATER, END, OK, True)],
        ),
        (
            "a reset shows the alert was broken before it, though it broke before the window",
            None,
            _control((MID, ControlChangeKind.RESET, PlatformAlertState.BROKEN)),
            {"": OK},
            None,
            [(START, MID, PlatformAlertState.BROKEN, True), (MID, END, OK, True)],
        ),
        (
            "a snooze ends when it runs out, though no check moved",
            None,
            _control((MID, ControlChangeKind.SNOOZE)),
            {"": OK},
            LATER,
            [(START, MID, OK, True), (MID, LATER, SNOOZED, True), (LATER, END, OK, True)],
        ),
    ]
)
def test_state_timeline(
    _name: str,
    history: PlatformAlertHistory | None,
    control: PlatformControlHistory | None,
    current_group_states: dict[str, PlatformAlertState],
    snooze_until: datetime | None,
    expected: list[tuple[datetime, datetime, PlatformAlertState, bool]],
) -> None:
    intervals = state_timeline(
        history=history,
        control=control,
        current_group_states=current_group_states,
        current_enabled=True,
        snooze_until=snooze_until,
        window=(START, END),
    )

    assert intervals == tuple(
        StateInterval(start=start, end=end, state=state, enabled=enabled) for start, end, state, enabled in expected
    )
