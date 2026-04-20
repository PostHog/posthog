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
