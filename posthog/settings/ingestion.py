import os

import structlog

from posthog.settings.utils import get_from_env, get_list, get_set

logger = structlog.get_logger(__name__)

INGESTION_LAG_METRIC_TEAM_IDS = get_list(os.getenv("INGESTION_LAG_METRIC_TEAM_IDS", ""))

# KEEP IN SYNC WITH plugin-server/src/config/config.ts
BUFFER_CONVERSION_SECONDS = get_from_env("BUFFER_CONVERSION_SECONDS", default=60, type_cast=int)

REPLAY_RETENTION_DAYS_MIN = get_from_env("REPLAY_RETENTION_DAYS_MIN", type_cast=int, default=30)
REPLAY_RETENTION_DAYS_MAX = get_from_env("REPLAY_RETENTION_DAYS_MAX", type_cast=int, default=90)
REPLAY_CAPTURE_ENDPOINT = os.getenv("REPLAY_CAPTURE_ENDPOINT", "/s/")

CAPTURE_INTERNAL_URL = os.getenv("CAPTURE_INTERNAL_URL", "http://localhost:8010")
CAPTURE_REPLAY_INTERNAL_URL = os.getenv("CAPTURE_REPLAY_INTERNAL_URL", "http://localhost:8010")
CAPTURE_INTERNAL_MAX_WORKERS = get_from_env("CAPTURE_INTERNAL_MAX_WORKERS", type_cast=int, default=16)

NEW_ANALYTICS_CAPTURE_ENDPOINT = os.getenv("NEW_CAPTURE_ENDPOINT", "/i/v0/e/")
NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS = get_set(os.getenv("NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS", ""))

ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS = get_set(os.getenv("ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS", ""))

PERSONS_DB_REROUTE_ENABLED = get_from_env("PERSONS_DB_REROUTE_ENABLED", type_cast=bool, default=False)
