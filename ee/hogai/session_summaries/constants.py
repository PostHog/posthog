# LLM models
SESSION_SUMMARIES_STREAMING_MODEL = "gpt-4.1"  # Model to use when streaming (usually, single session summaries)
SESSION_SUMMARIES_SYNC_MODEL = (
    "o3"  # Model to use for sync calls (usually, reasoning, like pattern extraction for session group summaries)
)
SESSION_SUMMARIES_REASONING_EFFORT = "medium"
SESSION_SUMMARIES_TEMPERATURE = 0.1  # Reduce hallucinations, but >0 to allow for some creativity

# Temporal
# How long to store the DB data in Redis within Temporal session summaries jobs
SESSION_SUMMARIES_DB_DATA_REDIS_TTL = 60 * 60 * 24  # 24 hours to keep alive for retries and long-running workflows
FAILED_SESSION_SUMMARIES_MIN_RATIO = 0.5  # If less than 50% of session group summaries succeed, stop the workflow
FAILED_PATTERNS_ASSIGNMENT_MIN_RATIO = 0.75  # If less than 75% of patterns assignment succeed, stop the workflow

# Patterns
PATTERNS_ASSIGNMENT_CHUNK_SIZE = 10  # How many single-session-summaries to feed at once to assign events to patterns
