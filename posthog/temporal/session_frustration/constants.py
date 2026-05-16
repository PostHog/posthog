"""Configuration constants for session frustration detection."""

from datetime import timedelta

# Schedule
SCHEDULE_INTERVAL = timedelta(hours=1)

# ClickHouse query
LOOKBACK_WINDOW = timedelta(hours=2)
MIN_FRUSTRATION_SCORE = 5  # Same as FrustrationSignalsPlaylistSource
MAX_EVENTS_PER_TEAM = 50
SESSION_COMPLETED_THRESHOLD_MINUTES = 30  # No activity for 30 min = session ended

# Redis dedup
REDIS_KEY_PREFIX = "session_frustration"
SESSION_DEDUP_TTL = timedelta(days=7)
PERSON_FREQUENCY_CAP_TTL = timedelta(hours=72)

# Coordinator
MAX_CONCURRENT_TEAMS = 50

# Event
EVENT_NAME = "$session_frustration_detected"
EVENT_SOURCE = "session_frustration_detection"
DETECTION_METHOD = "heuristic_v1"
