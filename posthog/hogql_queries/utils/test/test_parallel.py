import contextvars
from functools import partial

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from posthog.hogql_queries.utils.parallel import run_in_parallel_threads

_probe: contextvars.ContextVar[str] = contextvars.ContextVar("parallel_test_probe", default="unset")


def test_worker_spans_stay_inside_the_callers_trace() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")

    def work(index: int) -> None:
        with tracer.start_as_current_span(f"series_{index}"):
            pass

    with tracer.start_as_current_span("caller") as caller:
        caller_context = caller.get_span_context()
        run_in_parallel_threads([partial(work, index) for index in range(3)])

    series = [span for span in exporter.get_finished_spans() if span.name.startswith("series_")]
    assert len(series) == 3
    for span in series:
        # Checked before the span_id read below, so a worker that lost the context reports the
        # missing parent rather than an AttributeError on None. This also narrows the type, which
        # is what the union-attr check needs.
        assert span.parent is not None, f"{span.name} is its own trace root, so the context was lost"
        assert span.parent.span_id == caller_context.span_id
        assert span.context.trace_id == caller_context.trace_id


def test_workers_read_the_callers_context_and_cannot_rebind_it() -> None:
    token = _probe.set("from_caller")
    seen: list[str] = []

    def work(index: int) -> None:
        seen.append(_probe.get())
        _probe.set(f"from_worker_{index}")

    try:
        run_in_parallel_threads([partial(work, index) for index in range(2)])

        assert seen == ["from_caller", "from_caller"]
        assert _probe.get() == "from_caller"
    finally:
        _probe.reset(token)
