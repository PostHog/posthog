import pytest

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from posthog.celery import _tag_celery_span_with_team_id


def _provider_with_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


@pytest.mark.parametrize(
    "task_kwargs,expected",
    [
        ({"team_id": 4242}, 4242),
        ({"team_id": 1, "other": "x"}, 1),
        ({"other": "x"}, None),
        ({"team_id": "4242"}, None),
        ({"team_id": True}, None),
        (None, None),
    ],
)
def test_tag_celery_span_with_team_id(task_kwargs, expected):
    provider, exporter = _provider_with_exporter()
    with provider.get_tracer("test").start_as_current_span("run/some_task"):
        _tag_celery_span_with_team_id(task_kwargs)

    spans = [s for s in exporter.get_finished_spans() if s.name == "run/some_task"]
    assert len(spans) == 1
    attributes = spans[0].attributes or {}
    if expected is None:
        assert "team_id" not in attributes
    else:
        assert attributes["team_id"] == expected
