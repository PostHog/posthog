import pytest

from posthog.test.waiting import wait_until


def test_wait_until_returns_once_the_condition_holds() -> None:
    calls = iter([False, False, True])
    wait_until(lambda: next(calls), interval=0)


def test_wait_until_fails_when_the_deadline_passes() -> None:
    with pytest.raises(AssertionError, match="the queue never drained within 0.01s"):
        wait_until(lambda: False, timeout=0.01, interval=0, message="the queue never drained")
