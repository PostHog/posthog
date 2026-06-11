"""
WSGI config for posthog project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/howto/deployment/wsgi/
"""

import gc
import os

from django.core.wsgi import get_wsgi_application

from posthog.caching.redis_cluster_connection_factory import prewarm_query_cache_cluster_in_background
from posthog.continuous_profiling import start_continuous_profiling
from posthog.otel_instrumentation import initialize_otel

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
    # Building it here keeps the cost at worker boot, behind readiness. (Verified against
    # the production image: Unit 1.35 loads this module once per application process — no
    # prototype fork/COW — so each worker pays its own boot, exactly like before the lazy
    # router.) Non-web processes (celery, temporal, migrate, shell) never load this module
    # and keep the lazy win.
    from django.urls import get_resolver

    _ = get_resolver().url_patterns  # property access triggers the build
finally:
    gc.freeze()
    gc.enable()

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
        _prewarmed = True
    return _django_application(environ, start_response)
