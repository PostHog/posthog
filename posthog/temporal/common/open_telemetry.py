import typing
import collections.abc

from django.conf import settings

from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import Decision, Sampler, SamplingResult, _get_from_env_or_default
from opentelemetry.trace import Link, SpanKind, TraceState, get_current_span, set_tracer_provider
from opentelemetry.util.types import Attributes
from temporalio.contrib.opentelemetry import create_tracer_provider

from posthog.otel_instrumentation import INSTRUMENTORS


class WorkflowIdPrefixSampler(Sampler):
    """Always sample spans of Temporal workflows whose ID starts with a configured prefix.

    Spans emitted by Temporal's `OpenTelemetryPlugin` (via its `OpenTelemetryInterceptor`)
    carry a `temporalWorkflowID` attribute at span creation time (both `RunWorkflow:*` and
    `RunActivity:*` spans), which is the only moment a sampler can see attributes.
    Matching spans are always sampled; all other spans
    are delegated, so the env-driven ratio sampling (`OTEL_TRACES_SAMPLER` /
    `OTEL_TRACES_SAMPLER_ARG`) still applies to non-matching traffic.

    The prefix check runs before any parent-based delegation on purpose: activity spans carry
    the workflow ID themselves, so a matching workflow's activities are captured even if the
    parent's sampled flag wasn't propagated to the worker running them.
    """

    def __init__(self, prefixes: collections.abc.Iterable[str], delegate: Sampler) -> None:
        self._prefixes = tuple(prefixes)
        self._delegate = delegate

    def should_sample(
        self,
        parent_context: Context | None,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: Attributes = None,
        links: typing.Sequence[Link] | None = None,
        trace_state: TraceState | None = None,
    ) -> SamplingResult:
        workflow_id = (attributes or {}).get("temporalWorkflowID")
        if isinstance(workflow_id, str) and workflow_id.startswith(self._prefixes):
            parent_span_context = get_current_span(parent_context).get_span_context()
            return SamplingResult(
                Decision.RECORD_AND_SAMPLE,
                attributes,
                parent_span_context.trace_state if parent_span_context.is_valid else None,
            )

        return self._delegate.should_sample(parent_context, trace_id, name, kind, attributes, links, trace_state)

    def get_description(self) -> str:
        return f"WorkflowIdPrefixSampler{{prefixes={list(self._prefixes)},delegate={self._delegate.get_description()}}}"


def initialize_otel(service_name: str, libraries_to_instrument: collections.abc.Iterable[str] = ()) -> None:
    """Initialize Open Telemetry for Temporal workers.

    This uses Temporal's replay-safe tracer provider which is meant to work with
    Temporal's `OpenTelemetryPlugin`.
    """
    resource = Resource.create(attributes={"service.name": service_name})

    # `sampler=None` keeps the provider's default env-driven sampling behavior.
    sampler: Sampler | None = None
    if prefixes := settings.TEMPORAL_OTEL_ALWAYS_SAMPLE_WORKFLOW_ID_PREFIXES:
        sampler = WorkflowIdPrefixSampler(prefixes, delegate=_get_from_env_or_default())

    provider = create_tracer_provider(resource=resource, sampler=sampler)

    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    set_tracer_provider(provider)

    for lib in libraries_to_instrument:
        if instrument := INSTRUMENTORS.get(lib.lower()):
            instrument(provider)
