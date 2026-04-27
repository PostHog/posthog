import os

# Django Imports
from django.conf import settings
from django.core.asgi import get_asgi_application
from django.http.response import HttpResponse

# Structlog Import
import structlog

os.environ["DJANGO_SETTINGS_MODULE"] = "posthog.settings"
# Try to ensure SERVER_GATEWAY_INTERFACE is fresh for the child process
if "SERVER_GATEWAY_INTERFACE" in os.environ:
    del os.environ["SERVER_GATEWAY_INTERFACE"]  # Delete if inherited
os.environ["SERVER_GATEWAY_INTERFACE"] = "ASGI"  # Set definitively

# Get a structlog logger for asgi.py's own messages
logger = structlog.get_logger(__name__)

# NOTE: OTel and continuous profiling init is deferred to first request via
# _ensure_post_fork_init() below. Both start background threads (OTel's
# BatchSpanProcessor, Pyroscope's native profiler) that cannot survive
# fork(). Nginx Unit loads this module in a "prototype" process and then
# forks workers from it — the forked children inherit dead thread state and
# corrupted mutexes, causing SIGSEGV / SIGABRT on the worker. Deferring to
# first request ensures threads start in the actual worker process.
# This is safe across all server types: Granian uses spawn (not fork),
# runserver is single-process, and Celery doesn't import this file.
_post_fork_initialized = False


def _ensure_post_fork_init():
    global _post_fork_initialized
    if _post_fork_initialized:
        return

    from posthog.continuous_profiling import start_continuous_profiling
    from posthog.otel_instrumentation import initialize_otel

    start_continuous_profiling()
    initialize_otel()
    _post_fork_initialized = True


# Django doesn't support lifetime requests and raises an exception
# when it receives them. This creates a lot of noise in error tracking so
# intercept these requests and return a 501 error without raising an exception
def lifetime_wrapper(func):
    async def inner(scope, receive, send):
        if scope["type"] != "http":
            return HttpResponse(status=501)
        # Synchronous and blocks the first request (~1s for gRPC channel +
        # instrumentor patching). Acceptable: Unit workers handle one request
        # at a time, so there's no event-loop concurrency to stall, and this
        # only runs once per worker lifetime.
        _ensure_post_fork_init()
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
