import contextvars
from functools import partial

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from posthog.hogql_queries.utils.parallel import run_in_parallel_threads

_probe: contextvars.ContextVar[str] = contextvars.ContextVar("parallel_test_probe", default="unset")


def test_worker_spans_stay_inside_the_callers_trace():
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
    assert {span.context.trace_id for span in series} == {caller_context.trace_id}
    parents = [span.parent for span in series]
    assert all(parent is not None for parent in parents)
    assert {parent.span_id for parent in parents if parent is not None} == {caller_context.span_id}


def test_workers_read_the_callers_context_and_cannot_write_back():
    _probe.set("from_caller")
    seen: list[str] = []

    def work(index: int) -> None:
        seen.append(_probe.get())
        _probe.set(f"from_worker_{index}")

    run_in_parallel_threads([partial(work, index) for index in range(2)])

    assert seen == ["from_caller", "from_caller"]
    assert _probe.get() == "from_caller"
