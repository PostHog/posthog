import os
import atexit
import typing
import logging

from django.http import HttpRequest, HttpResponse

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.kafka import KafkaInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span
from opentelemetry.util.http import sanitize_method

# Get a structlog logger for this module's own messages
logger = structlog.get_logger(__name__)


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


def initialize_otel():
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

        # shutdown_on_exit=False: the SDK's own atexit hook calls provider.shutdown(),
        # which joins the BatchSpanProcessor export thread WITHOUT a timeout. If the
        # OTLP collector is unreachable, that thread sits in the gRPC exporter's
        # retry/backoff loop (~63s of sleeps per batch, and the exporter's shutdown
        # flag is only set after the join returns), so every process exit hangs until
        # SIGKILL — under granian this turns each worker stop into a
        # "refused to gracefully stop" hard kill. A bounded force_flush gives spans
        # their best shot at export and then lets the process exit; the export thread
        # is a daemon, so skipping shutdown() leaks nothing at exit.
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
        RedisInstrumentor().instrument(tracer_provider=provider)
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


def instrument_requests_client(provider: trace.TracerProvider):
    try:
        RequestsInstrumentor().instrument(tracer_provider=provider)
        logger.info("otel_instrumentation_attempt", instrumentor="RequestsInstrumentor", status="success")
    except Exception as e:
        logger.exception(
            "otel_instrumentation_attempt", instrumentor="RequestsInstrumentor", status="error", exc_info=e
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
