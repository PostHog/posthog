import os

from posthog.settings.utils import get_from_env, get_list

INGESTION_LAG_METRIC_TEAM_IDS = get_list(os.getenv("INGESTION_LAG_METRIC_TEAM_IDS", ""))

# KEEP IN SYNC WITH plugin-server/src/config/config.ts
BUFFER_CONVERSION_SECONDS = get_from_env("BUFFER_CONVERSION_SECONDS", default=60, type_cast=int)

LIGHTWEIGHT_CAPTURE_ENDPOINT_ENABLED_TOKENS = get_list(os.getenv("LIGHTWEIGHT_CAPTURE_ENDPOINT_ENABLED_TOKENS", ""))

# Keep in sync with plugin-server
EVENTS_DEAD_LETTER_QUEUE_STATSD_METRIC = "events_added_to_dead_letter_queue"
