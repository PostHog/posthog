import gc
import os

# Django Imports
from django.conf import settings
from django.core.asgi import get_asgi_application

# Structlog Import
import structlog

os.environ["DJANGO_SETTINGS_MODULE"] = "posthog.settings"
# Try to ensure SERVER_GATEWAY_INTERFACE is fresh for the child process
if "SERVER_GATEWAY_INTERFACE" in os.environ:
    del os.environ["SERVER_GATEWAY_INTERFACE"]  # Delete if inherited
os.environ["SERVER_GATEWAY_INTERFACE"] = "ASGI"  # Set definitively

# Get a structlog logger for asgi.py's own messages
logger = structlog.get_logger(__name__)

# NOTE: OTel, continuous profiling, and the web-memory sampler init are deferred to first
# request via _ensure_post_fork_init() below. They start background threads (OTel's
# BatchSpanProcessor, Pyroscope's native profiler, the sampler's loop) that cannot survive
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

    from posthog.caching.redis_cluster_connection_factory import prewarm_query_cache_cluster_in_background
    from posthog.continuous_profiling import start_continuous_profiling
    from posthog.otel_instrumentation import initialize_otel
    from posthog.web_memory_probe import install_memory_probe_handler
    from posthog.web_memory_sampler import start_web_memory_sampler

    start_continuous_profiling()
    initialize_otel()
    prewarm_query_cache_cluster_in_background()
    # Production runs ASGI, so the sampler — previously only started from wsgi.py — never
    # ran in prod, leaving posthog_web_worker_rss_mb empty. Start it here, post-fork.
    start_web_memory_sampler()
    # Register the on-demand SIGUSR2 memory probe here too — not because of fork-unsafe
    # threads (it starts none), but because signal handlers must be set on the worker's
    # main thread, which this init runs on. Inert unless WEB_MEMORY_PROBE_ENABLED is set.
    install_memory_probe_handler()
    _post_fork_initialized = True


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


def task_run_event_ingest_wrapper(func):
    async def inner(scope, receive, send):
        from products.tasks.backend.facade.streams import handle_task_run_event_ingest

        if await handle_task_run_event_ingest(scope, receive, send):
            return

        return await func(scope, receive, send)

    return inner


# Boot allocations are almost all permanent, so cyclic GC during django.setup() only adds
# pauses (~300ms). Disable it for the boot, then freeze the survivors so later full
# collections skip them — which also maximizes copy-on-write sharing when a prototype
# process forks workers. See docs/internal/django-startup-time.md.
gc.disable()
try:
    application = lifetime_wrapper(self_capture_wrapper(task_run_event_ingest_wrapper(get_asgi_application())))

    # Resolve the URLconf now, at module load — the lazy API router otherwise builds on
    # each worker's first live request (probes short-circuit in middleware and never warm
    # it). See the matching block in wsgi.py for the full reasoning.
    from django.urls import get_resolver

    _ = get_resolver().url_patterns  # property access triggers the build
finally:
    gc.freeze()
    gc.enable()
