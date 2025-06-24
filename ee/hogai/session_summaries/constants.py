SESSION_SUMMARIES_STREAMING_MODEL = "gpt-4.1"  # Model to use when streaming (usually, single session summaries)
SESSION_SUMMARIES_SYNC_MODEL = (
    "o3"  # Model to use for sync calls (usually, reasoning, like pattern extraction for session group summaries)
)
SESSION_SUMMARIES_REASONING_EFFORT = "medium"
SESSION_SUMMARIES_TEMPERATURE = 0.1  # Reduce hallucinations, but >0 to allow for some creativity
FAILED_SESSION_SUMMARIES_MIN_RATIO = 0.5  # If more than 50% of session group fail, stop the workflow
