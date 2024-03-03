from typing import List

from posthog.settings import get_from_env, get_list
from posthog.utils import str_to_bool

# TRICKY: we saw unusual memory usage behavior in EU clickhouse cluster
# when allowing use of denormalized properties in some session replay event queries
# it is likely this can be returned to the default of True in future but would need careful monitoring
ALLOW_DENORMALIZED_PROPS_IN_LISTING = get_from_env("ALLOW_DENORMALIZED_PROPS_IN_LISTING", False, type_cast=str_to_bool)

# realtime snapshot loader tries REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_MAX times
# it waits for REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_TIMEOUT_SECONDS between the first 3 attempts
# and REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_TIMEOUT_SECONDS * 2 between the remainder
# so with the default values, it will try for 1.8 seconds before giving up (0.2, 0.2, 0.2, 0.4, 0.4, 0.4)
REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_MAX = get_from_env("REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_MAX", 6, type_cast=int)

REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_TIMEOUT_SECONDS = get_from_env(
    "REALTIME_SNAPSHOTS_FROM_REDIS_ATTEMPT_TIMEOUT_SECONDS", 0.2, type_cast=float
)


RECORDINGS_INGESTER_URL = get_from_env("RECORDINGS_INGESTER_URL", "")

REPLAY_EMBEDDINGS_ALLOWED_TEAMS: List[str] = get_list(get_from_env("REPLAY_EMBEDDINGS_ALLOWED_TEAM", "", type_cast=str))
# how many recordings are passed into the loading task
# there is only one CH write per the N recordings passed in
REPLAY_EMBEDDINGS_BATCH_SIZE = get_from_env("REPLAY_EMBEDDINGS_BATCH_SIZE", 20, type_cast=int)
# how many recordings are fetched at once
# these are split into tasks of REPLAY_EMBEDDINGS_BATCH_SIZE each
REPLAY_EMBEDDINGS_QUERY_PAGE_SIZE = get_from_env("REPLAY_EMBEDDINGS_QUERY_PAGE_SIZE", 25000, type_cast=int)
REPLAY_EMBEDDINGS_MIN_DURATION_SECONDS = get_from_env("REPLAY_EMBEDDINGS_MIN_DURATION_SECONDS", 30, type_cast=int)
REPLAY_EMBEDDINGS_CALCULATION_CELERY_INTERVAL_SECONDS = get_from_env(
    "REPLAY_EMBEDDINGS_CALCULATION_CELERY_INTERVAL_SECONDS", 3600, type_cast=int
)
