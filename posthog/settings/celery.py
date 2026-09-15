import os
from datetime import timedelta
from typing import Optional

from kombu import Exchange, Queue

from posthog.settings.base_variables import TEST
from posthog.settings.data_stores import REDIS_URL
from posthog.settings.utils import get_from_env

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
]
CELERY_BROKER_URL = REDIS_URL  # celery connects to redis
CELERY_BEAT_MAX_LOOP_INTERVAL = get_from_env(
    "CELERY_BEAT_MAX_LOOP_INTERVAL", 30, type_cast=int
)  # sleep max 30sec before checking for new periodic events
CELERY_RESULT_BACKEND = REDIS_URL  # stores results for lookup when processing
CELERY_IGNORE_RESULT = True  # only applies to delay(), must do @shared_task(ignore_result=True) for apply_async
CELERY_RESULT_EXPIRES = timedelta(days=4)  # expire tasks after 4 days instead of the default 1
REDBEAT_LOCK_TIMEOUT = get_from_env("REDBEAT_LOCK_TIMEOUT", 45, type_cast=int)  # keep distributed beat lock for 45sec
# redbeat extends this lock on every tick and does not catch the failure, so a beat process that
# loses the lock exits. A deployment that runs one beat has nothing to coordinate with, so set
# REDBEAT_LOCK_KEY to an empty string to run without the lock. Read with os.getenv because
# get_from_env cannot tell an empty variable from an absent one.
REDBEAT_LOCK_KEY: Optional[str] = os.getenv("REDBEAT_LOCK_KEY", "redbeat::lock") or None

if TEST:
    import celery

    celery.current_app.conf.CELERY_ALWAYS_EAGER = True
    celery.current_app.conf.CELERY_EAGER_PROPAGATES_EXCEPTIONS = True
