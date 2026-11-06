import os
import atexit
import typing
import logging
from collections.abc import Iterator, Sequence
from urllib.parse import urlsplit, urlunsplit

from django.http import HttpRequest, HttpResponse

import structlog
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor, RequestInfo
from opentelemetry.instrumentation.kafka import KafkaInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE
from opentelemetry.trace import Link, Span, SpanKind, StatusCode
from opentelemetry.util._decorator import _agnosticcontextmanager
from opentelemetry.util.http import sanitize_method
from opentelemetry.util.types import Attributes
from requests import PreparedRequest

# Get a structlog logger for this module's own messages
logger = structlog.get_logger(__name__)

_OUTBOUND_URL_ATTRIBUTE_KEYS = ("http.url", "url.full")


def _otel_django_request_hook(span: Span, request: HttpRequest) -> None:
    if span and span.is_recording():
        actual_path = request.path
        http_method = request.method or ""
        span.set_attribute("http.method", http_method)
        span.set_attribute("http.url", actual_path)
        # span.update_name(f"{http_method} {actual_path}") # Use with caution - high cardinality


def _otel_django_response_hook(span: Span, request: HttpRequest, response: HttpResponse) -> None:
    if not span or not span.is_recording():
        return

    span.set_attribute("http.status_code", response.status_code)
    route = getattr(getattr(request, "resolver_match", None), "route", None)
    if not route:
        return

    http_method = sanitize_method((request.method or "").strip())
    span.update_name("HTTP" if http_method == "_OTHER" else f"{http_method} {route}")


def _otel_redis_request_hook(span: Span, instance: object, args: Sequence[object], kwargs: dict[str, object]) -> None:
    """Tag cluster-client spans with the connection attributes the instrumentor leaves off.

    opentelemetry-instrumentation-redis reads `db.system` and `net.peer.*` off
    `client.connection_pool.connection_kwargs`, and returns early for any client that has no
    `connection_pool`. `redis.cluster.RedisCluster` keeps per-node pools under `nodes_manager`
    instead, so its spans arrive carrying a command name and nothing else, which hides them from
    every query that selects Redis spans by `db.system` or groups them by host.

    A command's shard is chosen inside `execute_command`, after this hook runs, so `net.peer.name`
    is a node from the client's own topology: it identifies the cluster, not the hop that served
    the command. `db.redis.cluster` marks that distinction.
    """
    # This runs inside the traced Redis call, and the instrumentor does not guard hook calls, so a
    # raise here would fail the command itself. An unfamiliar client shape degrades to an untagged
    # span instead, which is the behavior without this hook.
    try:
        if not span or not span.is_recording() or hasattr(instance, "connection_pool"):
            return

        startup_nodes = getattr(getattr(instance, "nodes_manager", None), "startup_nodes", None)
        if not startup_nodes:
            return

        span.set_attribute("db.system", "redis")
        span.set_attribute("db.redis.cluster", True)
        span.set_attribute("net.transport", "ip_tcp")

        node = next(iter(startup_nodes.values()), None)
        host = getattr(node, "host", None)
        port = getattr(node, "port", None)
        if host:
            span.set_attribute("net.peer.name", host)
        if port:
            span.set_attribute("net.peer.port", port)
    except Exception:
        logger.debug("otel_redis_request_hook_failed", exc_info=True)


def _url_origin(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return urlunsplit((parts.scheme, parts.netloc.rpartition("@")[2], "", "", ""))


def _replace_span_url_with_origin(span: Span, url: str) -> None:
    if not span.is_recording():
        return
    origin = _url_origin(url)
    for key in _OUTBOUND_URL_ATTRIBUTE_KEYS:
        span.set_attribute(key, origin)


def _otel_requests_request_hook(span: Span, request: PreparedRequest) -> None:
    _replace_span_url_with_origin(span, request.url or "")


def _otel_httpx_request_hook(span: Span, request: RequestInfo) -> None:
    _replace_span_url_with_origin(span, str(request.url))


async def _otel_httpx_async_request_hook(span: Span, request: RequestInfo) -> None:
    _otel_httpx_request_hook(span, request)


class _ExceptionTypeOnlyTracer(trace.Tracer):
    def __init__(self, tracer: trace.Tracer) -> None:
        self._tracer = tracer

    def start_span(
        self,
        name: str,
        context: Context | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Attributes = None,
        links: Sequence[Link] | None = None,
        start_time: int | None = None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
    ) -> Span:
        return self._tracer.start_span(
            name,
            context,
            kind,
            attributes,
            links,
            start_time,
            record_exception=False,
            set_status_on_exception=False,
        )

    @_agnosticcontextmanager
    def start_as_current_span(
        self,
        name: str,
        context: Context | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Attributes = None,
        links: Sequence[Link] | None = None,
        start_time: int | None = None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
        end_on_exit: bool = True,
    ) -> Iterator[Span]:
        with self._tracer.start_as_current_span(
            name,
            context,
            kind,
            attributes,
            links,
            start_time,
            record_exception=False,
            set_status_on_exception=False,
            end_on_exit=end_on_exit,
        ) as span:
            try:
                yield span
            except Exception as error:
                span.set_attribute(ERROR_TYPE, type(error).__name__)
                span.set_status(StatusCode.ERROR)
                raise


class _ExceptionTypeOnlyTracerProvider(trace.TracerProvider):
    def __init__(self, provider: trace.TracerProvider) -> None:
        self._provider = provider

    def get_tracer(
        self,
        instrumenting_module_name: str,
        instrumenting_library_version: str | None = None,
        schema_url: str | None = None,
        attributes: Attributes = None,
    ) -> trace.Tracer:
        tracer = self._provider.get_tracer(
            instrumenting_module_name, instrumenting_library_version, schema_url, attributes
        )
        return _ExceptionTypeOnlyTracer(tracer)


def initialize_otel(*, instrument_outbound_calls: bool = False) -> None:
    # App tracing targets a real OTLP collector (dev/prod). In tests, booting the app
    # (e.g. posthog/test/test_asgi_lifespan.py imports posthog.asgi) would otherwise arm a
    # process-wide span exporter to the SDK default localhost:4317 with no collector there,
    # so the flush at pytest shutdown retries with exponential backoff and stalls the run by
    # minutes. Skip app instrumentation in tests WITHOUT touching OTEL_SDK_DISABLED, so tests
    # that build their own in-memory TracerProvider still record spans (test_auth_spans,
    # test_celery_span_team_id, test_routing). TEST is forced on by settings/overrides.py
    # before any app import runs.
    if os.environ.get("TEST") == "1":
        return

    # --- BEGIN FORCED OTEL DEBUG LOGGING ---
    otel_python_log_level_env = os.environ.get("OTEL_PYTHON_LOG_LEVEL", "info").lower()
    effective_log_level = logging.DEBUG if otel_python_log_level_env == "debug" else logging.INFO

    root_logger = logging.getLogger()
    # Set root logger level only if we are making it more verbose than it might already be.
    # Or if it's not set (None), then set it.
    # This avoids overriding a potentially more restrictive level set elsewhere.
    if root_logger.level == logging.NOTSET or effective_log_level < root_logger.level:
        root_logger.setLevel(effective_log_level)

    django_instr_logger = logging.getLogger("opentelemetry.instrumentation.django")
    django_instr_logger.setLevel(logging.DEBUG)  # Force this to DEBUG
    django_instr_logger.propagate = True  # Ensure its messages go to root handlers for structlog processing

    logger.info(
        "otel_sdk_logging_config_from_instrumentation_module",
        note="Configured OTel SDK log levels. Formatting via django-structlog.",
        root_logger_current_level=logging.getLevelName(root_logger.level),
        root_logger_target_level=logging.getLevelName(effective_log_level),
        django_instrumentor_logger_target_level="DEBUG",
        otel_python_log_level_env=otel_python_log_level_env,
    )
    # --- END FORCED OTEL DEBUG LOGGING ---

    if os.environ.get("OTEL_SDK_DISABLED", "false").lower() != "true":
        service_name = os.environ.get("OTEL_SERVICE_NAME", "posthog-django-default")
        resource = Resource.create(attributes={"service.name": service_name})

        # Let OpenTelemetry SDK handle sampling configuration via OTEL_TRACES_SAMPLER and OTEL_TRACES_SAMPLER_ARG
        # This allows parentbased_traceidratio and other standard sampler types
        sampler_type = os.environ.get("OTEL_TRACES_SAMPLER", "parentbased_traceidratio")  # Respect parent decisions
        sampler_arg = os.environ.get("OTEL_TRACES_SAMPLER_ARG", "0")

        logger.info(
            "otel_sampler_configured",
            sampler_type=sampler_type,
            sampler_arg=sampler_arg if sampler_arg else "default",
            note="Using OpenTelemetry standard sampling configuration",
            source_module="otel_instrumentation",
        )

        # The SDK's atexit shutdown joins the exporter thread without a timeout.
        # A bounded flush keeps an unreachable collector from delaying worker exit.
        # The exporter thread is a daemon, so it can exit with the process.
        provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        otlp_exporter = OTLPSpanExporter()  # Assumes OTLP endpoint is configured via env vars
        processor = BatchSpanProcessor(otlp_exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        atexit.register(lambda: provider.force_flush(timeout_millis=5_000))
        logger.info(
            "otel_core_components_initialized_successfully",
            service_name=service_name,
            source_module="otel_instrumentation",
        )

        instrument_django(provider)
        instrument_celery(provider)
        instrument_redis(provider)
        instrument_psycopg(provider)
        instrument_kafka(provider)
        instrument_aiokafka(provider)
        if instrument_outbound_calls:
            instrument_requests_client(provider)
            instrument_httpx_client(provider)
            instrument_botocore(provider)

        logger.info(
            "otel_manual_init_status_from_instrumentation_module",
            service_name=service_name,
            detail="OpenTelemetry manually initialized with hooks (no manual middleware entry in settings.MIDDLEWARE)",
        )
    else:
        logger.info(
            "otel_manual_init_status_from_instrumentation_module",
            status="disabled",
            reason="OTEL_SDK_DISABLED environment variable is set to true",
        )


def instrument_django(provider: trace.TracerProvider):
    try:
        DjangoInstrumentor().instrument(
            tracer_provider=provider,
            request_hook=_otel_django_request_hook,
            response_hook=_otel_django_response_hook,
        )
        logger.info("otel_instrumentation_attempt", instrumentor="DjangoInstrumentor", status="success")
    except Exception as e:
        logger.exception("otel_instrumentation_attempt", instrumentor="DjangoInstrumentor", status="error", exc_info=e)


def instrument_celery(provider: trace.TracerProvider):
    try:
        CeleryInstrumentor().instrument(tracer_provider=provider)
        logger.info("otel_instrumentation_attempt", instrumentor="CeleryInstrumentor", status="success")
    except Exception as e:
        logger.exception("otel_instrumentation_attempt", instrumentor="CeleryInstrumentor", status="error", exc_info=e)


def instrument_redis(provider: trace.TracerProvider):
    try:
        RedisInstrumentor().instrument(tracer_provider=provider, request_hook=_otel_redis_request_hook)
        logger.info("otel_instrumentation_attempt", instrumentor="RedisInstrumentor", status="success")
    except Exception as e:
        logger.exception("otel_instrumentation_attempt", instrumentor="RedisInstrumentor", status="error", exc_info=e)


def instrument_psycopg(provider: trace.TracerProvider):
    try:
        PsycopgInstrumentor().instrument(tracer_provider=provider, enable_commenter=False)
        logger.info(
            "otel_instrumentation_attempt",
            instrumentor="PsycopgInstrumentor",
            status="success",
            note="SQLCommenter enabled for diagnostics",
        )
    except Exception as e:
        logger.exception("otel_instrumentation_attempt", instrumentor="PsycopgInstrumentor", status="error", exc_info=e)


def instrument_kafka(provider: trace.TracerProvider):
    try:
        KafkaInstrumentor().instrument(tracer_provider=provider)
        logger.info("otel_instrumentation_attempt", instrumentor="KafkaInstrumentor", status="success")
    except Exception as e:
        logger.exception("otel_instrumentation_attempt", instrumentor="KafkaInstrumentor", status="error", exc_info=e)


def instrument_aiokafka(provider: trace.TracerProvider):
    try:
        AIOKafkaInstrumentor().instrument(tracer_provider=provider)
        logger.info("otel_instrumentation_attempt", instrumentor="AIOKafkaInstrumentor", status="success")
    except Exception as e:
        logger.exception(
            "otel_instrumentation_attempt", instrumentor="AIOKafkaInstrumentor", status="error", exc_info=e
        )


def instrument_aiohttp_client(provider: trace.TracerProvider):
    try:
        AioHttpClientInstrumentor().instrument(tracer_provider=provider)
        logger.info("otel_instrumentation_attempt", instrumentor="AioHttpClientInstrumentor", status="success")
    except Exception as e:
        logger.exception(
            "otel_instrumentation_attempt", instrumentor="AioHttpClientInstrumentor", status="error", exc_info=e
        )


def instrument_requests_client(provider: trace.TracerProvider) -> None:
    try:
        RequestsInstrumentor().instrument(
            tracer_provider=_ExceptionTypeOnlyTracerProvider(provider),
            request_hook=_otel_requests_request_hook,
        )
        logger.info("otel_instrumentation_attempt", instrumentor="RequestsInstrumentor", status="success")
    except Exception as e:
        logger.exception(
            "otel_instrumentation_attempt", instrumentor="RequestsInstrumentor", status="error", exc_info=e
        )


def instrument_httpx_client(provider: trace.TracerProvider) -> None:
    try:
        HTTPXClientInstrumentor().instrument(
            tracer_provider=_ExceptionTypeOnlyTracerProvider(provider),
            request_hook=_otel_httpx_request_hook,
            async_request_hook=_otel_httpx_async_request_hook,
        )
        logger.info("otel_instrumentation_attempt", instrumentor="HTTPXClientInstrumentor", status="success")
    except Exception as e:
        logger.exception(
            "otel_instrumentation_attempt", instrumentor="HTTPXClientInstrumentor", status="error", exc_info=e
        )


def instrument_botocore(provider: trace.TracerProvider) -> None:
    try:
        BotocoreInstrumentor().instrument(tracer_provider=_ExceptionTypeOnlyTracerProvider(provider))
        logger.info("otel_instrumentation_attempt", instrumentor="BotocoreInstrumentor", status="success")
    except Exception as e:
        logger.exception(
            "otel_instrumentation_attempt", instrumentor="BotocoreInstrumentor", status="error", exc_info=e
        )


INSTRUMENTORS: dict[str, typing.Callable[[trace.TracerProvider], None]] = {
    "django": instrument_django,
    "psycopg": instrument_psycopg,
    "redis": instrument_redis,
    "kafka": instrument_kafka,
    "aiokafka": instrument_aiokafka,
    "aiohttp-client": instrument_aiohttp_client,
    "requests": instrument_requests_client,
}
