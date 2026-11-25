from datetime import UTC, datetime, timedelta

import pytest

from products.ai_observability.backend.logic.traces.turn_timing import (
    SILENCE_MS,
    SLOW_WAIT_MS,
    TurnTiming,
    TurnVerdict,
    turn_verdicts,
)

T0 = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def at(ms: float, wait_ms: float | None = None) -> TurnTiming:
    return TurnTiming(started_at=T0 + timedelta(milliseconds=ms), wait_ms=wait_ms)


@pytest.mark.parametrize(
    "wait_ms, slow",
    [(None, False), (SLOW_WAIT_MS - 1, False), (SLOW_WAIT_MS, True)],
    ids=["unmeasured", "just under the threshold", "at the threshold"],
)
def test_a_wait_is_slow_from_the_threshold(wait_ms: float | None, slow: bool) -> None:
    assert turn_verdicts(None, [at(0, wait_ms)]) == [TurnVerdict(wait_slow=slow, silence_before_ms=None)]


@pytest.mark.parametrize(
    "previous, turn_ms, silence",
    [
        (None, SILENCE_MS * 5, None),
        (at(0), SILENCE_MS - 1, None),
        (at(0), SILENCE_MS, SILENCE_MS),
        (at(0, wait_ms=30_000), SILENCE_MS + 29_999, None),
        (at(0, wait_ms=1_500.5), SILENCE_MS + 2_000, SILENCE_MS + 500),
        (at(0.9), SILENCE_MS + 0.2, SILENCE_MS),
    ],
    ids=[
        "the session's first turn",
        "just under a minute",
        "a minute",
        "counted from the end of the previous answer",
        "rounded to the millisecond",
        "from whole milliseconds",
    ],
)
def test_a_silence_counts_from_the_previous_answer_and_shows_from_a_minute(
    previous: TurnTiming | None, turn_ms: float, silence: int | None
) -> None:
    [verdict] = turn_verdicts(previous, [at(turn_ms)])

    assert verdict.silence_before_ms == silence


def test_each_turn_follows_the_one_before_it_on_the_page() -> None:
    verdicts = turn_verdicts(at(0), [at(SILENCE_MS * 2), at(SILENCE_MS * 2 + 1), at(SILENCE_MS * 4)])

    assert [verdict.silence_before_ms for verdict in verdicts] == [SILENCE_MS * 2, None, SILENCE_MS * 2 - 1]
