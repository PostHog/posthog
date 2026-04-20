import time
import asyncio
import threading
import contextvars

import pytest

from posthog.temporal.data_imports.pipelines.pipeline.pipeline import async_iterate

_probe: contextvars.ContextVar[str | None] = contextvars.ContextVar("probe", default=None)


@pytest.mark.asyncio
async def test_async_iterate_propagates_contextvars_to_source_thread():
    # Regression: loop.run_in_executor does not propagate contextvars, so
    # logs emitted from inside a source's streaming generator used to lose
    # team_id / workflow_* and get silently dropped from the produce path.
    _probe.set("bound-value")

    def sync_gen():
        yield _probe.get()
        yield _probe.get()

    seen = [item async for item in async_iterate(sync_gen())]

    assert seen == ["bound-value", "bound-value"]


@pytest.mark.asyncio
async def test_async_iterate_context_snapshot_is_isolated_from_generator_mutations():
    _probe.set("outer")

    def sync_gen():
        _probe.set("inner")
        yield _probe.get()

    seen = [item async for item in async_iterate(sync_gen())]

    assert seen == ["inner"]
    # Caller's context is unaffected by mutations inside the generator.
    assert _probe.get() == "outer"


@pytest.mark.asyncio
async def test_async_iterate_context_mutation_persists_across_iterations():
    # The same context snapshot is reused for every iteration, so writes to
    # ContextVars inside one _next() persist into the next. Intentional:
    # matches pre-#46962 single-thread iteration semantics. Pinned here so
    # a future switch to per-iteration copy (e.g. asyncio.to_thread style)
    # becomes a loud test failure rather than a silent behavior change.
    _probe.set("outer")

    def sync_gen():
        _probe.set("inner")
        yield _probe.get()
        yield _probe.get()

    seen = [item async for item in async_iterate(sync_gen())]

    assert seen == ["inner", "inner"]
    assert _probe.get() == "outer"


@pytest.mark.asyncio
async def test_async_iterate_close_runs_when_cancelled_mid_iteration():
    # Regression: reusing the iteration ctx for the finally-block _close
    # caused RuntimeError on cancellation (ctx still entered by the
    # in-flight _next), which skipped iterator.close() and leaked DB /
    # network resources. Using a fresh cleanup_ctx prevents that.
    closed_flag = threading.Event()

    class SlowIterator:
        def __iter__(self):
            return self

        def __next__(self):
            time.sleep(0.5)  # blocks long enough for cancellation to fire
            return 1

        def close(self):
            closed_flag.set()

    async def consume():
        async for _ in async_iterate(SlowIterator()):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)  # let the first _next actually enter ctx.run
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # close() must have run despite cancellation mid-iteration.
    assert closed_flag.wait(timeout=3.0), "iterator.close() was not called"
