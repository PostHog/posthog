import os

# Django Imports
from django.conf import settings
from django.core.asgi import get_asgi_application

# Structlog Import
import structlog

# PostHog OpenTelemetry Initialization
from posthog.otel_instrumentation import initialize_otel

os.environ["DJANGO_SETTINGS_MODULE"] = "posthog.settings"
# Try to ensure SERVER_GATEWAY_INTERFACE is fresh for the child process
if "SERVER_GATEWAY_INTERFACE" in os.environ:
    del os.environ["SERVER_GATEWAY_INTERFACE"]  # Delete if inherited
os.environ["SERVER_GATEWAY_INTERFACE"] = "ASGI"  # Set definitively

initialize_otel()  # Initialize OpenTelemetry first

# Get a structlog logger for asgi.py's own messages
logger = structlog.get_logger(__name__)


# Django 5 sends ASGI lifespan events during startup/shutdown. Earlier versions
# would raise when receiving them, so we intercept the handshake here and
# acknowledge it ourselves to avoid noisy errors while still delegating other
# scope types to Django.
def lifetime_wrapper(func):
    async def inner(scope, receive, send):
        scope_type = scope.get("type")

        if scope_type == "lifespan":
            while True:
                message = await receive()
                message_type = message.get("type")

                if message_type == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message_type == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
                else:
                    logger.warning("Received unexpected lifespan message", message_type=message_type)
        else:
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
