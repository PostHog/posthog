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
from posthog.web_memory_probe import install_memory_probe_handler
from posthog.web_memory_sampler import start_web_memory_sampler

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ.setdefault("SERVER_GATEWAY_INTERFACE", "WSGI")

start_continuous_profiling()
initialize_otel()

# Boot allocations are almost all permanent, so cyclic GC during django.setup() only adds
# pauses (~300ms). Disable it for the boot, then freeze the survivors so later full
# collections skip them — which also maximizes copy-on-write sharing when a prototype
# process forks workers. See docs/internal/django-startup-time.md.
gc.disable()
try:
    _django_application = get_wsgi_application()

    # Resolve the URLconf now, at module load. The lazy API router otherwise builds on
    # each worker's FIRST LIVE REQUEST — k8s probes (/_livez, /_readyz) short-circuit in
    # middleware and never warm it — costing seconds per worker after every deploy.
    # Building it here keeps the cost to the prototype-process boot: Unit forks workers
    # from that prototype after the module loads, so the built router lands in the frozen
    # heap and is copy-on-write shared across all forked workers. Non-web processes
    # (celery, temporal, migrate, shell) never load this module and keep the lazy win.
    from django.urls import get_resolver

    _ = get_resolver().url_patterns  # property access triggers the build
finally:
    gc.freeze()
    gc.enable()


# A web worker logs `web_worker_started` once, here at the end of boot. Nginx Unit recycles a
# worker after NGINX_UNIT_REQUEST_LIMIT requests, and the kernel respawns one whenever a worker
# is OOM-killed (SIGKILL is uncatchable, so the kill itself can't be logged from inside the
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
            request_limit=os.getenv("NGINX_UNIT_REQUEST_LIMIT"),
            pod=os.getenv("K8S_POD_NAME") or os.getenv("HOSTNAME"),
        )
    except Exception:
        pass


_log_web_worker_started()

# Nginx Unit forks workers from a prototype process that imported this module, so
# the query_cache RedisCluster must be discovered post-fork: a client built here at
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
        # Start the RSS sampler post-fork, here in the worker. Unit forks workers from a
        # prototype that already imported this module, and a thread started pre-fork does
        # not survive into the worker — starting it on the worker's first call samples the
        # process that actually serves requests and grows toward the OOM limit.
        start_web_memory_sampler()
        # Register the SIGUSR2 memory probe on the same post-fork path (see asgi.py). On a
        # single-threaded Unit worker this runs on the main thread; if Unit serves the app
        # from a worker thread the install no-ops gracefully. Inert unless the env flag is set.
        install_memory_probe_handler()
        _prewarmed = True
    return _django_application(environ, start_response)
