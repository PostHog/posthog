from typing import List

from posthog.settings import get_from_env
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

REPLAY_LISTING_DISTINCT_IDS_FROM_EVENTS_OPTIMISATION_TEAM_IDS: List[int] = []
try:
    REPLAY_LISTING_DISTINCT_IDS_FROM_EVENTS_OPTIMISATION_TEAM_IDS = [
        int(x)
        for x in get_from_env("REPLAY_LISTING_DISTINCT_IDS_FROM_EVENTS_OPTIMISATION_TEAM_IDS", "", type_cast=str).split(
            ","
        )
        if x
    ]
except Exception:
    print(  # noqa: T201 - print is fine here
        "Error parsing REPLAY_LISTING_DISTINCT_IDS_FROM_EVENTS_OPTIMISATION_TEAM_IDS, must be comma separated list of integers"
    )  # noqa: T201 - print is fine here
