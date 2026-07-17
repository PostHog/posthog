from datetime import timedelta

from kombu import Exchange, Queue

from posthog.settings.base_variables import TEST
from posthog.settings.data_stores import REDIS_URL

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
    "posthog.api.oauth.cimd",
    "posthog.caching.warming",
    "posthog.email",
    "posthog.models.product_intent.product_intent",
    "posthog.models.scoping",
    "posthog.scoping_audit",
]
CELERY_BROKER_URL = REDIS_URL  # celery connects to redis
CELERY_BEAT_MAX_LOOP_INTERVAL = 30  # sleep max 30sec before checking for new periodic events
CELERY_RESULT_BACKEND = REDIS_URL  # stores results for lookup when processing
CELERY_IGNORE_RESULT = True  # only applies to delay(), must do @shared_task(ignore_result=True) for apply_async
CELERY_RESULT_EXPIRES = timedelta(days=4)  # expire tasks after 4 days instead of the default 1
REDBEAT_LOCK_TIMEOUT = 45  # keep distributed beat lock for 45sec

if TEST:
    import celery

    celery.current_app.conf.CELERY_ALWAYS_EAGER = True
    celery.current_app.conf.CELERY_EAGER_PROPAGATES_EXCEPTIONS = True
