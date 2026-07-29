import contextvars

import pytest

from posthog.sync import _RESTORE_CONTEXT_ATTEMPTS, _make_resilient_restore_context


def _transient_error() -> RuntimeError:
    return RuntimeError("dictionary changed size during iteration")


def test_retries_transient_gc_race_and_succeeds() -> None:
    calls = 0

    def flaky(context: contextvars.Context) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _transient_error()

    _make_resilient_restore_context(flaky)(contextvars.copy_context())

    assert calls == 2


def test_reraises_when_race_never_clears() -> None:
    calls = 0

    def always_racy(context: contextvars.Context) -> None:
        nonlocal calls
        calls += 1
        raise _transient_error()

    with pytest.raises(RuntimeError, match="changed size during iteration"):
        _make_resilient_restore_context(always_racy)(contextvars.copy_context())

    assert calls == _RESTORE_CONTEXT_ATTEMPTS


def test_does_not_swallow_unrelated_runtime_errors() -> None:
    def unrelated(context: contextvars.Context) -> None:
        raise RuntimeError("something else went wrong")

    with pytest.raises(RuntimeError, match="something else went wrong"):
        _make_resilient_restore_context(unrelated)(contextvars.copy_context())
