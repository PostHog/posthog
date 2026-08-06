from dataclasses import dataclass

import pytest
from unittest.mock import AsyncMock, MagicMock

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from temporalio.worker import ExecuteActivityInput, ExecuteWorkflowInput

from posthog.temporal.common.posthog_client import (
    _PostHogClientActivityInboundInterceptor,
    _PostHogClientWorkflowInterceptor,
)


@dataclass
class _InputWithTeam:
    team_id: int


@dataclass
class _InputWithoutTeam:
    something_else: str


def _provider_with_exporter() -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def _span_named(exporter: InMemorySpanExporter, name: str):
    spans = [s for s in exporter.get_finished_spans() if s.name == name]
    assert len(spans) == 1
    return spans[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "interceptor_cls,input_spec,execute_method,span_name",
    [
        (_PostHogClientActivityInboundInterceptor, ExecuteActivityInput, "execute_activity", "RunActivity"),
        (_PostHogClientWorkflowInterceptor, ExecuteWorkflowInput, "execute_workflow", "RunWorkflow"),
    ],
)
class TestPostHogClientTeamIdTagging:
    async def test_tags_team_id_on_current_span(self, interceptor_cls, input_spec, execute_method, span_name):
        provider, exporter = _provider_with_exporter()
        next_interceptor = AsyncMock()
        getattr(next_interceptor, execute_method).return_value = "result"
        interceptor = interceptor_cls(next_interceptor)

        mock_input = MagicMock(spec=input_spec)
        mock_input.args = [_InputWithTeam(team_id=4242)]

        with provider.get_tracer("test").start_as_current_span(span_name):
            result = await getattr(interceptor, execute_method)(mock_input)

        assert result == "result"
        assert _span_named(exporter, span_name).attributes["team_id"] == 4242

    async def test_no_team_id_when_input_lacks_field(self, interceptor_cls, input_spec, execute_method, span_name):
        provider, exporter = _provider_with_exporter()
        next_interceptor = AsyncMock()
        getattr(next_interceptor, execute_method).return_value = "result"
        interceptor = interceptor_cls(next_interceptor)

        mock_input = MagicMock(spec=input_spec)
        mock_input.args = [_InputWithoutTeam(something_else="x")]

        with provider.get_tracer("test").start_as_current_span(span_name):
            await getattr(interceptor, execute_method)(mock_input)

        assert "team_id" not in (_span_named(exporter, span_name).attributes or {})
