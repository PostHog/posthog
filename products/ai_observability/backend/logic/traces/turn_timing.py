from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Final

from posthog.dataclasses import frozen

SLOW_WAIT_MS: Final = 10_000
SILENCE_MS: Final = 60_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@frozen
class TurnTiming:
    started_at: datetime
    wait_ms: float | None


@frozen
class TurnVerdict:
    wait_slow: bool
    silence_before_ms: int | None


def is_slow_wait(wait_ms: float | None) -> bool:
    return wait_ms is not None and wait_ms >= SLOW_WAIT_MS


def silence_before_ms(previous: TurnTiming | None, turn: TurnTiming) -> int | None:
    """The time between the previous turn's answer and this turn's start, when it is long enough to show."""
    if previous is None:
        return None
    previous_end = _epoch_ms(previous.started_at) + (previous.wait_ms or 0)
    silence = _epoch_ms(turn.started_at) - previous_end
    return round(silence) if silence >= SILENCE_MS else None


def turn_verdicts(previous: TurnTiming | None, turns: Sequence[TurnTiming]) -> list[TurnVerdict]:
    """One verdict per turn, in order. `previous` is the turn before the first one, None when it starts the session."""
    return [
        TurnVerdict(wait_slow=is_slow_wait(turn.wait_ms), silence_before_ms=silence_before_ms(before, turn))
        for before, turn in zip([previous, *turns], turns)
    ]


def _epoch_ms(moment: datetime) -> int:
    # Whole milliseconds, as a browser parses the timestamp.
    return (moment.astimezone(UTC) - _EPOCH) // timedelta(milliseconds=1)
