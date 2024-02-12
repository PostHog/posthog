import os

import structlog

from posthog.settings.utils import get_from_env, get_list, get_set
from posthog.utils import str_to_bool

logger = structlog.get_logger(__name__)

INGESTION_LAG_METRIC_TEAM_IDS = get_list(os.getenv("INGESTION_LAG_METRIC_TEAM_IDS", ""))

# KEEP IN SYNC WITH plugin-server/src/config/config.ts
BUFFER_CONVERSION_SECONDS = get_from_env("BUFFER_CONVERSION_SECONDS", default=60, type_cast=int)


# A list of <team_id:distinct_id> pairs (in the format 2:myLovelyId) that we should use
# random partitioning for when producing events to the Kafka topic consumed by the plugin server.
# This is a measure to handle hot partitions in ad-hoc cases.
EVENT_PARTITION_KEYS_TO_OVERRIDE = get_list(os.getenv("EVENT_PARTITION_KEYS_TO_OVERRIDE", ""))

# Keep in sync with plugin-server
EVENTS_DEAD_LETTER_QUEUE_STATSD_METRIC = "events_added_to_dead_letter_queue"

QUOTA_LIMITING_ENABLED = get_from_env("QUOTA_LIMITING_ENABLED", False, type_cast=str_to_bool)

PARTITION_KEY_AUTOMATIC_OVERRIDE_ENABLED = get_from_env(
    "PARTITION_KEY_AUTOMATIC_OVERRIDE_ENABLED", type_cast=bool, default=False
)
PARTITION_KEY_BUCKET_CAPACITY = get_from_env("PARTITION_KEY_BUCKET_CAPACITY", type_cast=int, default=1000)
PARTITION_KEY_BUCKET_REPLENTISH_RATE = get_from_env(
    "PARTITION_KEY_BUCKET_REPLENTISH_RATE", type_cast=float, default=1.0
)

REPLAY_RETENTION_DAYS_MIN = get_from_env("REPLAY_RETENTION_DAYS_MIN", type_cast=int, default=30)
REPLAY_RETENTION_DAYS_MAX = get_from_env("REPLAY_RETENTION_DAYS_MAX", type_cast=int, default=90)

NEW_ANALYTICS_CAPTURE_ENDPOINT = os.getenv("NEW_CAPTURE_ENDPOINT", "/i/v0/e/")
NEW_ANALYTICS_CAPTURE_TEAM_IDS = get_set(os.getenv("NEW_ANALYTICS_CAPTURE_TEAM_IDS", ""))
NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS = get_set(os.getenv("NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS", ""))
NEW_ANALYTICS_CAPTURE_SAMPLING_RATE = get_from_env("NEW_ANALYTICS_CAPTURE_SAMPLING_RATE", type_cast=float, default=1.0)

NEW_CAPTURE_ENDPOINTS_INCLUDED_TEAM_IDS = get_set(os.getenv("NEW_CAPTURE_ENDPOINTS_INCLUDED_TEAM_IDS", ""))
NEW_CAPTURE_ENDPOINTS_SAMPLING_RATE = get_from_env("NEW_CAPTURE_ENDPOINTS_SAMPLING_RATE", type_cast=float, default=1.0)

ELEMENT_CHAIN_AS_STRING_TEAMS = get_set(os.getenv("ELEMENT_CHAIN_AS_STRING_TEAMS", ""))
ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS = get_set(os.getenv("ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS", ""))
