from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from kombu import Exchange, Queue

from posthog.settings.base_variables import TEST
from posthog.settings.data_stores import REDIS_URL
from posthog.settings.utils import get_from_env, str_to_bool

# Freeze the worker parent's objects before the prefork pool forks, so the pool children keep sharing
# that memory instead of copying it on their first garbage collection. Hobby turns it on. The name
# avoids the CELERY_ prefix, which Celery reads as its own configuration.
GC_FREEZE_BEFORE_POOL_FORK = get_from_env("GC_FREEZE_BEFORE_POOL_FORK", False, type_cast=str_to_bool)

# Only listen to the default queue "celery", unless overridden via the CLI
CELERY_QUEUES = (Queue("celery", Exchange("celery"), "celery"),)
CELERY_DEFAULT_QUEUE = "celery"
# Tasks defined OUTSIDE the autodiscovered `<app>/tasks.py` convention only register
# when their module happens to get imported. That's fine under the normal worker (the
# app loads them transitively) and under item-level test sharding (every shard imports
# the whole tree), but NOT under --split-granularity=file, where a shard imports only
# its own files — so e.g. test_all_posthog_tasks_registered saw an incomplete registry.
# List them here so Celery's import_default_modules() registers them deterministically
# (worker + tests), independent of what else got imported.
CELERY_IMPORTS: list[str] = [
    "ee.tasks.quota_limiting",
    "posthog.api.oauth.cimd",
    "posthog.caching.warming",
    "posthog.email",
    "posthog.models.product_intent.product_intent",
    "posthog.models.scoping",
    "posthog.query_cache.tasks",
    "posthog.scoping_audit",
    # Not a `<app>/tasks.py`, so autodiscovery walks past it — the app package holds a `tasks/`
    # namespace package instead, and importing that doesn't reach the module inside.
    "products.tasks.backend.tasks.tasks",
    "products.legal_documents.backend.tasks.tasks",
    "products.aeo.backend.tasks.tasks",
    "products.business_knowledge.backend.tasks.tasks",
    "products.alerts.backend.tasks.tasks",
]


_CERT_REQS_ALIASES = {"cert_required": "required", "cert_optional": "optional", "cert_none": "none"}


def with_tls_verification(url: str | None) -> str | None:
    """Make a rediss:// URL verify the certificate and hostname, in a form Celery, kombu and redis-py all accept.

    Without ssl_cert_reqs, kombu skips certificate checks and the Redis result backend refuses to start.
    redis-py accepts only the lowercase ssl_cert_reqs values, and checks the hostname only when asked.
    """
    if not url or urlsplit(url).scheme != "rediss":
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    cert_reqs = query.get("ssl_cert_reqs", "required").lower()
    query["ssl_cert_reqs"] = _CERT_REQS_ALIASES.get(cert_reqs, cert_reqs)
    if query["ssl_cert_reqs"] == "required":
        query.setdefault("ssl_check_hostname", "true")
    return urlunsplit(parts._replace(query=urlencode(list(query.items()))))


def _celery_redis_url(env_key: str, default: str | None) -> str | None:
    """Read an optional Celery Redis URL. Only explicitly set URLs get the TLS rewrite, so REDIS_URL behaves as before."""
    url = get_from_env(env_key, optional=True)
    return with_tls_verification(url) if url else default


# Not named CELERY_BROKER_URL etc.: Celery reads those from the environment ahead of these settings.
CELERY_BROKER_URL = _celery_redis_url("CELERY_BROKER_REDIS_URL", REDIS_URL)
CELERY_BROKER_READ_URL = _celery_redis_url("CELERY_BROKER_READ_REDIS_URL", None)
CELERY_BROKER_WRITE_URL = _celery_redis_url("CELERY_BROKER_WRITE_REDIS_URL", None)
# Pinned so a broker move doesn't move the scheduler lock and run two schedulers.
CELERY_REDBEAT_REDIS_URL = _celery_redis_url("CELERY_REDBEAT_REDIS_URL", REDIS_URL)

_broker_visibility_timeout_seconds = get_from_env(
    "CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS", optional=True, type_cast=int
)
if _broker_visibility_timeout_seconds is not None:
    CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": _broker_visibility_timeout_seconds}

CELERY_BEAT_MAX_LOOP_INTERVAL = 30  # sleep max 30sec before checking for new periodic events
CELERY_RESULT_BACKEND = _celery_redis_url("CELERY_RESULT_BACKEND_REDIS_URL", REDIS_URL)
CELERY_IGNORE_RESULT = True  # only applies to delay(), must do @shared_task(ignore_result=True) for apply_async
CELERY_RESULT_EXPIRES = timedelta(days=4)  # expire tasks after 4 days instead of the default 1
REDBEAT_LOCK_TIMEOUT = 45  # keep distributed beat lock for 45sec

if TEST:
    import celery

    celery.current_app.conf.CELERY_ALWAYS_EAGER = True
    celery.current_app.conf.CELERY_EAGER_PROPAGATES_EXCEPTIONS = True
