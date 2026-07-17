import json
import asyncio
import inspect

import pytest

import posthoganalytics
import temporalio.activity
from temporalio.testing import ActivityEnvironment

from posthog.temporal.common.scoped import scoped_temporal


def test_scoped_temporal_preserves_iscoroutinefunction() -> None:
    """This is the exact predicate Temporal uses at temporalio/worker/_activity.py:781
    to decide between async dispatch and the sync threadpool. If our wrapper fails it,
    Temporal routes the activity to the threadpool and the unawaited coroutine result
    fails JSON encoding — which is the production bug."""

    @scoped_temporal()
    async def my_activity(x: int) -> int:
        return x + 1

    assert inspect.iscoroutinefunction(my_activity)


def test_scoped_temporal_returns_unwrapped_value_when_awaited() -> None:
    """Awaiting a wrapped activity must yield the inner function's return value, not
    a nested coroutine — the latter is what Temporal's payload converter chokes on."""

    @scoped_temporal()
    async def my_activity(x: int) -> int:
        return x + 1

    assert asyncio.run(my_activity(41)) == 42


def test_scoped_temporal_rejects_sync_function() -> None:
    """Defensive: applying scoped_temporal to a sync def raises immediately at decoration
    time so misuse can't silently regress to the production failure mode."""

    def my_sync_activity(x: int) -> int:
        return x + 1

    with pytest.raises(TypeError, match="async function"):
        scoped_temporal()(my_sync_activity)  # type: ignore[arg-type]


def test_scoped_temporal_propagates_exceptions() -> None:
    @scoped_temporal()
    async def my_activity() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(my_activity())


def test_scoped_temporal_preserves_function_metadata() -> None:
    """functools.wraps copies __name__/__qualname__/__doc__ — needed so Temporal's
    activity registry resolves the right name."""

    @scoped_temporal()
    async def my_activity(x: int) -> int:
        """An activity."""
        return x + 1

    assert my_activity.__name__ == "my_activity"
    assert my_activity.__doc__ == "An activity."


# ---------------------------------------------------------------------------
# Regression tests for the upstream bug we shim around. If a future upstream
# release ships an async-aware scoped(), these turn red and prompt removing
# our wrapper.
# ---------------------------------------------------------------------------


def test_upstream_scoped_breaks_iscoroutinefunction_on_async_fn() -> None:
    """Documents the upstream bug in older SDKs while tolerating fixed SDKs."""

    @posthoganalytics.scoped()
    async def my_activity(x: int) -> int:
        return x + 1

    if inspect.iscoroutinefunction(my_activity):
        assert asyncio.run(my_activity(1)) == 2
        return

    coro = my_activity(1)
    try:
        assert inspect.iscoroutine(coro)
    finally:
        coro.close()


def test_upstream_scoped_result_fails_json_encoding() -> None:
    """Reproduce the old SDK failure while tolerating async-aware scoped()."""

    @posthoganalytics.scoped()
    async def my_activity(x: int) -> int:
        return x + 1

    result = my_activity(1)
    if inspect.iscoroutinefunction(my_activity):
        try:
            assert asyncio.run(result) == 2
        finally:
            if inspect.iscoroutine(result):
                result.close()
        return

    try:
        with pytest.raises(TypeError, match="coroutine"):
            json.dumps(result)
    finally:
        result.close()


# ---------------------------------------------------------------------------
# End-to-end via Temporal's real ActivityEnvironment dispatch path.
#
# ActivityEnvironment._Activity.__init__ runs the same iscoroutinefunction check
# the production worker uses, then routes to the async-await path or the
# sync-threadpool path accordingly. So these tests exercise the same dispatch
# that failed in production.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scoped_temporal_routes_through_async_temporal_dispatch() -> None:
    @temporalio.activity.defn
    @scoped_temporal()
    async def echo_activity(x: int) -> int:
        return x * 2

    assert await ActivityEnvironment().run(echo_activity, 21) == 42


# ---------------------------------------------------------------------------
# Smoke test against a real converted activity from the signals package.
# ---------------------------------------------------------------------------


def test_real_signals_activity_is_dispatched_as_async() -> None:
    """Sanity check that a real activity from products/signals/, with the production
    decorator stack (@temporalio.activity.defn + @scoped_temporal()), passes the
    dispatch predicate — i.e., the bug that surfaced in the production trace cannot
    recur for activities decorated this way."""
    from products.signals.backend.temporal.summary import mark_report_failed_activity

    assert inspect.iscoroutinefunction(mark_report_failed_activity)
