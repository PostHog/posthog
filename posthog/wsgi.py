"""
WSGI config for posthog project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

from posthog.caching.redis_cluster_connection_factory import prewarm_query_cache_cluster_in_background
from posthog.continuous_profiling import start_continuous_profiling
from posthog.otel_instrumentation import initialize_otel

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ.setdefault("SERVER_GATEWAY_INTERFACE", "WSGI")

start_continuous_profiling()
initialize_otel()
_django_application = get_wsgi_application()

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
