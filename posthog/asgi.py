import logging
import os

# OpenTelemetry Imports
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.django import DjangoInstrumentor

# Django Imports
from django.conf import settings
from django.core.asgi import get_asgi_application
from django.http.response import HttpResponse

# Structlog Import
import structlog

# --- BEGIN FORCED OTEL DEBUG LOGGING ---
# This section ensures OTel SDK's own logs are emitted at the correct level.
# Formatting will be handled by the project-wide django-structlog setup.

otel_python_log_level_env = os.environ.get("OTEL_PYTHON_LOG_LEVEL", "info").lower()
effective_log_level = logging.DEBUG if otel_python_log_level_env == "debug" else logging.INFO

# Get the root logger and set its level
root_logger = logging.getLogger()
root_logger.setLevel(effective_log_level)

# Configure opentelemetry.instrumentation.django logger specifically
django_instr_logger = logging.getLogger("opentelemetry.instrumentation.django")
django_instr_logger.setLevel(logging.DEBUG)  # Force this to DEBUG
django_instr_logger.propagate = True  # Ensure its messages go to root handlers

# Get a structlog logger for asgi.py's own messages
logger = structlog.get_logger(__name__)

# Log a message (using structlog) to confirm this basic logging setup is working
logger.info(
    "otel_sdk_logging_config",
    note="Configured OTel SDK log levels. Formatting via django-structlog.",
    root_logger_target_level=logging.getLevelName(effective_log_level),
    django_instrumentor_logger_target_level="DEBUG",
    otel_python_log_level_env=otel_python_log_level_env,
)
# --- END FORCED OTEL DEBUG LOGGING ---

# OpenTelemetry Manual Initialization - START


# Define the hooks before they are used by the instrumentor
def _otel_django_request_hook(span, request):
    if span and span.is_recording():
        actual_path = request.path
        http_method = request.method
        span.set_attribute("http.method", http_method)
        span.set_attribute("http.url", actual_path)
        # span.update_name(f"{http_method} {actual_path}") # Use with caution - high cardinality


def _otel_django_response_hook(span, request, response):
    if span and span.is_recording():
        span.set_attribute("http.status_code", response.status_code)


# Initialize OpenTelemetry only if not already done
if os.environ.get("OTEL_SDK_DISABLED", "false").lower() != "true":  # Allow disabling via env var
    service_name = os.environ.get("OTEL_SERVICE_NAME", "posthog-django-default")  # Fallback
    resource = Resource.create(attributes={"service.name": service_name})

    provider = TracerProvider(resource=resource)
    otlp_exporter = OTLPSpanExporter()
    processor = BatchSpanProcessor(otlp_exporter)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    DjangoInstrumentor().instrument(
        tracer_provider=provider, request_hook=_otel_django_request_hook, response_hook=_otel_django_response_hook
    )
    logger.info(
        "otel_manual_init_status",
        service_name=service_name,
        detail="OpenTelemetry manually initialized with hooks (no manual middleware entry in settings.MIDDLEWARE)",
    )
else:
    logger.info(
        "otel_manual_init_status", status="disabled", reason="OTEL_SDK_DISABLED environment variable is set to true"
    )
# OpenTelemetry Manual Initialization - END


os.environ["DJANGO_SETTINGS_MODULE"] = "posthog.settings"
# Try to ensure SERVER_GATEWAY_INTERFACE is fresh for the child process
if "SERVER_GATEWAY_INTERFACE" in os.environ:
    del os.environ["SERVER_GATEWAY_INTERFACE"]  # Delete if inherited
os.environ["SERVER_GATEWAY_INTERFACE"] = "ASGI"  # Set definitively


# Django doesn't support lifetime requests and raises an exception
# when it receives them. This creates a lot of noise in sentry so
# intercept these requests and return a 501 error without raising an exception
def lifetime_wrapper(func):
    async def inner(scope, receive, send):
        if scope["type"] != "http":
            # Note: Returning HttpResponse directly in an ASGI app might not be ideal
            # if the server expects ASGI message format.
            # However, for a simple 501, it might work or be handled by the ASGI server.
            # A more ASGI-native way would be:
            # await send({
            #     'type': 'http.response.start',
            #     'status': 501,
            #     'headers': [[b'content-type', b'text/plain']],
            # })
            # await send({
            #     'type': 'http.response.body',
            #     'body': b'Not Implemented',
            #     'more_body': False,
            # })
            # For now, keeping original HttpResponse approach for simplicity unless it causes issues.
            return HttpResponse(status=501)
        return await func(scope, receive, send)

    return inner


# PostHogConfig.ready() handles setting the global analytics key in WSGI. The same code couldn't run
# in ASGI because ready() doesn't expose an async interface.
def self_capture_wrapper(func):
    if not settings.DEBUG or not settings.SELF_CAPTURE:
        return func

    async def inner(scope, receive, send):
        if not getattr(inner, "debug_analytics_initialized", False):
            from posthog.utils import initialize_self_capture_api_token

            await initialize_self_capture_api_token()
            # Set a flag to indicate that the analytics key has been set, so we don't run the code on every request.
            inner.debug_analytics_initialized = True  # type: ignore
        return await func(scope, receive, send)

    return inner


application = lifetime_wrapper(self_capture_wrapper(get_asgi_application()))
