"""
WSGI config for posthog project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/howto/deployment/wsgi/
"""

import gc
import os

from django.core.wsgi import get_wsgi_application

import structlog

from posthog.caching.redis_cluster_connection_factory import prewarm_query_cache_cluster_in_background
from posthog.continuous_profiling import start_continuous_profiling
from posthog.otel_instrumentation import initialize_otel
from posthog.warehouse_source_prewarm import prewarm_warehouse_source_registry
from posthog.web_bot_auth_keys import validate_configured_web_bot_auth_private_keys_in_background
from posthog.web_memory_probe import install_memory_probe_handler
from posthog.web_memory_sampler import start_web_memory_sampler

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ.setdefault("SERVER_GATEWAY_INTERFACE", "WSGI")

start_continuous_profiling()
initialize_otel()

# Boot allocations are almost all permanent, so cyclic GC during django.setup() only adds
# pauses (~300ms). Disable it for the boot, then freeze the survivors so later full
# collections skip them, which also maximizes copy-on-write sharing when a parent
# process forks workers. See docs/internal/django-startup-time.md.
gc.disable()
try:
    _django_application = get_wsgi_application()

    # Resolve the URLconf now, at module load. The lazy API router otherwise builds on
    # each worker's FIRST LIVE REQUEST — k8s probes (/_livez, /_readyz) short-circuit in
    # middleware and never warm it — costing seconds per worker after every deploy.
    # Building it here pays the cost once in the parent, whose frozen heap the workers
    # then share copy-on-write. Non-web processes
    # (celery, temporal, migrate, shell) never load this module and keep the lazy win.
    from django.urls import get_resolver

    _ = get_resolver().url_patterns  # property access triggers the build

    # Load the warehouse source catalog before this worker serves, so its first warehouse
    # query skips the multi-second import. No-op unless PREWARM_WAREHOUSE_SOURCE_REGISTRY
    # is set, which deployment config enables only for the Granian deployment that serves
    # warehouse queries; each Granian worker imports this module itself. Running inside
    # the GC window lands the catalog in the frozen heap, so future full collections
    # skip it.
    prewarm_warehouse_source_registry()
finally:
    gc.freeze()
    gc.enable()


# A web worker logs `web_worker_started` once, here at the end of boot. Granian recycles a
# worker once it passes GRANIAN_WORKERS_MAX_RSS, and respawns one whenever a worker is
# OOM-killed (SIGKILL is uncatchable, so the kill itself can't be logged from inside the
# worker). Either way the replacement boots and emits this line — so a burst of these on a pod
# is the in-app fingerprint of worker churn / OOM kills, queryable in PostHog even though the
# kill leaves no other application-level trace. Best-effort: never break worker startup.
def _log_web_worker_started() -> None:
    try:
        rss_mb: float | None
        try:
            with open("/proc/self/statm") as statm:
                rss_mb = int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
        except (OSError, ValueError, IndexError):
            rss_mb = None

        structlog.get_logger("posthog.wsgi").info(
            "web_worker_started",
            pid=os.getpid(),
            rss_mb=round(rss_mb, 1) if rss_mb is not None else None,
            max_rss_mb=os.getenv("GRANIAN_WORKERS_MAX_RSS"),
            pod=os.getenv("K8S_POD_NAME") or os.getenv("HOSTNAME"),
        )
    except Exception:
        pass


_log_web_worker_started()

# Workers are forked from a parent process that already imported this module, so the
# query_cache RedisCluster must be discovered post-fork: a client built here at
# import time would be inherited -- sockets and all -- by every worker. Defer the
# prewarm to the first request so discovery runs in the worker; the factory also
# pid-guards the cache as a backstop. (start_continuous_profiling/initialize_otel
# above still run pre-fork here, unlike asgi.py which defers them -- that is a
# separate, pre-existing concern, not addressed by this change.)
#
# Best-effort once-guard: a concurrent first-request race may spawn a couple of
# redundant prewarm threads, which is harmless -- prewarm is idempotent and the
# factory dedups discovery under its own lock -- so it intentionally takes no lock.
_prewarmed = False


def application(environ, start_response):
    global _prewarmed
    if not _prewarmed:
        prewarm_query_cache_cluster_in_background()
        validate_configured_web_bot_auth_private_keys_in_background()
        # A thread started before a fork does not survive into the worker, so start the
        # sampler here to measure the process that actually serves requests.
        start_web_memory_sampler()
        # Signal handlers install only from the main thread, so this logs a handled failure
        # when the server calls the app off it. Inert unless the env flag is set.
        install_memory_probe_handler()
        _prewarmed = True
    return _django_application(environ, start_response)
