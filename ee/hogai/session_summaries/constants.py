# LLM models
SESSION_SUMMARIES_STREAMING_MODEL = "gpt-4.1"  # Model to use when streaming (usually, single session summaries)
SESSION_SUMMARIES_STREAMING_MODELS = [SESSION_SUMMARIES_STREAMING_MODEL]
SESSION_SUMMARIES_SYNC_MODEL = (
    "o3"  # Model to use for sync calls (usually, reasoning, like pattern extraction for session group summaries)
)
SESSION_SUMMARIES_REASONING_MODELS = [SESSION_SUMMARIES_SYNC_MODEL]
SESSION_SUMMARIES_REASONING_EFFORT = "medium"
SESSION_SUMMARIES_TEMPERATURE = 0.1  # Reduce hallucinations, but >0 to allow for some creativity

# Summarization
HALLUCINATED_EVENTS_MIN_RATIO = 0.15  # If more than 15% of events in the summary hallucinated, fail the summarization
GROUP_SUMMARIES_MIN_SESSIONS = (
    5  # Minimum number of sessions to use group summary logic (find patterns) instead of summarizing them separately
)

# Temporal
# How long to store the DB data in Redis within Temporal session summaries jobs
SESSION_SUMMARIES_DB_DATA_REDIS_TTL = 60 * 60 * 24  # 24 hours to keep alive for retries and long-running workflows
FAILED_SESSION_SUMMARIES_MIN_RATIO = 0.5  # If less than 50% of session group summaries succeed, stop the workflow
FAILED_PATTERNS_ASSIGNMENT_MIN_RATIO = 0.75  # If less than 75% of patterns assignment succeed, stop the workflow

# Patterns
PATTERNS_ASSIGNMENT_CHUNK_SIZE = 10  # How many single-session-summaries to feed at once to assign events to patterns
PATTERNS_EXTRACTION_MAX_TOKENS = (
    150000  # Maximum tokens allowed for pattern extraction (below o3 model limit and within expected quality range)
)
SINGLE_ENTITY_MAX_TOKENS = 200000  # General limit to avoid hitting the o3 model limit, used in case of exceptions (like one session to large for a regular chunk)
FAILED_PATTERNS_EXTRACTION_MIN_RATIO = 0.75  # If less than 75% of pattern extraction chunks succeed, stop the workflow
