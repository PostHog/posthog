from datetime import UTC, datetime, timedelta

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import (
    ControlChangeKind,
    PlatformAlertHistory,
    PlatformControlChange,
    PlatformControlHistory,
    PlatformStateChange,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.alerts_platform.backend.logic.state_timeline import StateInterval, state_timeline

START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(hours=24)
MID = START + timedelta(hours=10)
LATER = START + timedelta(hours=15)

OK = PlatformAlertState.NOT_FIRING
FIRING = PlatformAlertState.FIRING


def _history(*changes: tuple[datetime, PlatformAlertState, PlatformAlertState]) -> PlatformAlertHistory:
    return PlatformAlertHistory(
        state_changes=tuple(
            PlatformStateChange(occurred_at=at, previous_state=before, state=after) for at, before, after in changes
        ),
        last_checked_at=END,
        last_error_message=None,
    )


def _control(
    *changes: tuple[datetime, ControlChangeKind], toggle_before: ControlChangeKind | None = None
) -> PlatformControlHistory:
    return PlatformControlHistory(
        changes=tuple(
            PlatformControlChange(occurred_at=at, evaluation_key="", kind=kind, previous_state=OK, state=OK)
            for at, kind in changes
        ),
        oldest_at=START,
        toggle_before=toggle_before,
    )


@parameterized.expand(
    [
        ("no history keeps the current state", None, None, FIRING, [(START, END, FIRING, True)]),
        (
            "a state change splits the window and seeds from the state before it",
            _history((MID, OK, FIRING)),
            None,
            FIRING,
            [(START, MID, OK, True), (MID, END, FIRING, True)],
        ),
        (
            "a disable splits the window and the alert was enabled before it",
            None,
            _control((MID, ControlChangeKind.DISABLE)),
            OK,
            [(START, MID, OK, True), (MID, END, OK, False)],
        ),
        (
            "a toggle before the window seeds the enabled setting",
            _history((MID, OK, FIRING)),
            _control((LATER, ControlChangeKind.ENABLE), toggle_before=ControlChangeKind.DISABLE),
            FIRING,
            [(START, MID, OK, False), (MID, LATER, FIRING, False), (LATER, END, OK, True)],
        ),
    ]
)
def test_state_timeline(
    _name: str,
    history: PlatformAlertHistory | None,
    control: PlatformControlHistory | None,
    current_state: PlatformAlertState,
    expected: list[tuple[datetime, datetime, PlatformAlertState, bool]],
) -> None:
    intervals = state_timeline(
        history=history, control=control, current_state=current_state, current_enabled=True, window=(START, END)
    )

    assert intervals == tuple(
        StateInterval(start=start, end=end, state=state, enabled=enabled) for start, end, state, enabled in expected
    )
