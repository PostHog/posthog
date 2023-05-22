import os

from posthog.settings.utils import get_from_env, get_list
from posthog.utils import str_to_bool

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

REPLAY_EVENT_MAX_SIZE = get_from_env("REPLAY_EVENT_MAX_SIZE", type_cast=int, default=1024 * 512)  # 512kb
REPLAY_EVENTS_NEW_CONSUMER_RATIO = get_from_env("REPLAY_EVENTS_NEW_CONSUMER_RATIO", type_cast=float, default=0.0)

if REPLAY_EVENTS_NEW_CONSUMER_RATIO > 1 or REPLAY_EVENTS_NEW_CONSUMER_RATIO < 0:
    logger.critical(
        "Environment variable REPLAY_EVENTS_NEW_CONSUMER_RATIO is not between 0 and 1. Setting to 0 to be safe."
    )
    REPLAY_EVENTS_NEW_CONSUMER_RATIO = 0

REPLAY_RETENTION_DAYS_MIN = 30
REPLAY_RETENTION_DAYS_MAX = 90

# Used to capture test cases for new capture, meant to be used locally only
DUMP_CAPTURE_TO_FILE = os.getenv("DUMP_CAPTURE_TO_FILE", "")
