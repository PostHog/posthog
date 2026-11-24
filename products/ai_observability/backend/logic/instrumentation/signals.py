from enum import StrEnum

FIRST_EVENT_FLOOR = 1


class SignalGrade(StrEnum):
    PENDING = "pending"
    MISSING = "missing"
    PRESENT = "present"


def grade_signal(*, events: int, floor: int, has_signal: bool) -> SignalGrade:
    """Grades whether a project sends a piece of instrumentation. Below `floor` events there is too little to tell."""
    if events < floor:
        return SignalGrade.PENDING
    return SignalGrade.PRESENT if has_signal else SignalGrade.MISSING


def answers_session(*, with_session: int, declining_session: int) -> bool:
    """Whether a project tells which session its traces belong to: some carry a session id, or it explicitly declined
    one (`event_declines_session`)."""
    return with_session > 0 or declining_session > 0
