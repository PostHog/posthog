SMALL_ORG_THRESHOLD = 20000
BATCH_SIZE = 10000
SAMPLING_PERCENTAGE = 10
CACHE_TTL_SECONDS = 12 * 60 * 60  # 12 hours
CACHE_KEY_PREFIX = "activity_log:details_fields"

# Re-exported from the model layer, which owns the retention policy shared with the SQL surface.
from posthog.models.activity_logging.retention import (  # noqa: E402
    ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_LIMIT,
    ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_UNIT,
)

__all__ = [
    "ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_LIMIT",
    "ADVANCED_ACTIVITY_LOGS_LOOKBACK_FALLBACK_UNIT",
    "BATCH_SIZE",
    "CACHE_KEY_PREFIX",
    "CACHE_TTL_SECONDS",
    "SAMPLING_PERCENTAGE",
    "SMALL_ORG_THRESHOLD",
]
