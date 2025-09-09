# LLM models
SESSION_SUMMARIES_STREAMING_MODEL = "gpt-4.1"  # Model to use when streaming (usually, single session summaries)
SESSION_SUMMARIES_SUPPORTED_STREAMING_MODELS = {SESSION_SUMMARIES_STREAMING_MODEL}
# Model to use for sync calls (usually, reasoning, like pattern extraction for session group summaries)
SESSION_SUMMARIES_SYNC_MODEL = "o3"
SESSION_SUMMARIES_SUPPORTED_REASONING_MODELS = {SESSION_SUMMARIES_SYNC_MODEL}
SESSION_SUMMARIES_REASONING_EFFORT = "medium"
SESSION_SUMMARIES_TEMPERATURE = 0.1  # Reduce hallucinations, but >0 to allow for some creativity

# Ensure to cut LLM response if longer than expected to avoid hanging connections
BASE_LLM_CALL_TIMEOUT_S = 600.0

# Summarization
MAX_SESSIONS_TO_SUMMARIZE = 100  # Maximum number of sessions to summarize at once
HALLUCINATED_EVENTS_MIN_RATIO = 0.15  # If more than 15% of events in the summary hallucinated, fail the summarization
# Minimum number of sessions to use group summary logic (find patterns) instead of summarizing them separately
GROUP_SUMMARIES_MIN_SESSIONS = 5

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
