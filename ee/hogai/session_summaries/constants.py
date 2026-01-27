# LLM models
SESSION_SUMMARIES_STREAMING_MODEL = "gpt-4.1"  # Model to use when streaming (usually, single session summaries)
SESSION_SUMMARIES_SUPPORTED_STREAMING_MODELS = {SESSION_SUMMARIES_STREAMING_MODEL}
# Model to use for sync calls (usually, reasoning, like pattern extraction for session group summaries)
SESSION_SUMMARIES_SYNC_MODEL = "o3"
SESSION_SUMMARIES_REASONING_EFFORT = "medium"
SESSION_SUMMARIES_SUPPORTED_REASONING_MODELS = {SESSION_SUMMARIES_SYNC_MODEL}
SESSION_SUMMARIES_TEMPERATURE = 0.1  # Reduce hallucinations, but >0 to allow for some creativity

# Ensure to cut LLM response if longer than expected to avoid hanging connections
BASE_LLM_CALL_TIMEOUT_S = 600.0

# Summarization
MAX_SESSIONS_TO_SUMMARIZE = 100  # Maximum number of sessions to summarize at once
HALLUCINATED_EVENTS_MIN_RATIO = 0.15  # If more than 15% of events in the summary hallucinated, fail the summarization
# Minimum number of sessions to use group summary logic (find patterns) instead of summarizing them separately
GROUP_SUMMARIES_MIN_SESSIONS = 5
# Don't include events that are happened before or after the replay started, or at the very start/end,
# as we can't verify them with videos confidently,iterate if we find a better way to generate Replay videos
SESSION_EVENTS_REPLAY_CUTOFF_MS = 5000
# Minimum session duration to have any event survive the cutoff filter (must be > 2x cutoff)
MIN_SESSION_DURATION_FOR_SUMMARY_MS = 2 * SESSION_EVENTS_REPLAY_CUTOFF_MS + 1
# Minimum session duration for video-based summarization, where we don't need (or want) to cut off anything
MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S = 15

# Temporal
SESSION_SUMMARIES_DB_DATA_REDIS_TTL = 60 * 60 * 24  # How long to store the DB data in Redis within Temporal jobs
FAILED_SESSION_SUMMARIES_MIN_RATIO = 0.5  # If less than 50% of session group summaries succeed, stop the workflow
FAILED_PATTERNS_ASSIGNMENT_MIN_RATIO = 0.75  # If less than 75% of patterns assignment succeed, stop the workflow
SESSION_GROUP_SUMMARIES_WORKFLOW_POLLING_INTERVAL_MS = 2000  # How often to poll for the workflow status

# Patterns
PATTERNS_ASSIGNMENT_CHUNK_SIZE = 10  # How many single-session-summaries to feed at once to assign events to patterns
# Maximum tokens allowed for pattern extraction (below o3 model limit and within expected quality range)
PATTERNS_EXTRACTION_MAX_TOKENS = 150000
SINGLE_ENTITY_MAX_TOKENS = 200000  # General limit to avoid hitting the o3 model limit, used in case of exceptions
FAILED_PATTERNS_EXTRACTION_MIN_RATIO = 0.75  # If less than 75% of pattern extraction chunks succeed
FAILED_PATTERNS_ASSIGNMENT_MIN_RATIO = 0.75  # If less than 75% of patterns assignment succeed
FAILED_PATTERNS_ENRICHMENT_MIN_RATIO = 0.75  # If less than 75% of patterns were enriched with the meta

# Logging
MAX_SESSION_IDS_COMBINED_LOGGING_LENGTH = 150  # Maximum string of combined session ids to log in a readable format

# Videos to validate issues in summaries
SECONDS_BEFORE_EVENT_FOR_VALIDATION_VIDEO = 7
VALIDATION_VIDEO_DURATION = 12
SESSION_VIDEO_RENDERING_DELAY = 2  # Don't analyze first seconds of the video, as it could include malformed frames
VALIDATION_VIDEO_PLAYBACK_SPEED = 8  # We don't need minor details, as LLM needs 1 frame per second
SHORT_VALIDATION_VIDEO_PLAYBACK_SPEED = (
    1  # For short videos (10s validation chunks), we should stick to "render fully", instead of speed
)
FAILED_MOMENTS_MIN_RATIO = 0.5  # If less than 50% of moments failed to generate videos, fail the analysis
EXPIRES_AFTER_DAYS = 90  # How long to store the videos used for validation
DEFAULT_VIDEO_EXPORT_MIME_TYPE = "video/webm"
DEFAULT_VIDEO_UNDERSTANDING_MODEL = "gemini-3-flash-preview"
