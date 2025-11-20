"""Constants for batch trace summarization workflows."""

# Window processing configuration
DEFAULT_MAX_TRACES_PER_WINDOW = 100  # Max traces to process per window (conservative for worst-case 30s/trace)
DEFAULT_BATCH_SIZE = 10  # Number of traces to process in parallel per batch
DEFAULT_MODE = "minimal"  # Summary detail level: 'minimal' or 'detailed'
DEFAULT_WINDOW_MINUTES = 60  # Process traces from last N minutes (matches schedule frequency)
DEFAULT_WORKFLOW_MODEL = "gpt-5-mini"  # Default LLM model for workflow (slower but better than UI default)

# Timeout configuration (in seconds)
SAMPLE_TIMEOUT_SECONDS = 300  # 5 minutes for sampling query
FETCH_HIERARCHY_TIMEOUT_SECONDS = 30  # 30 seconds per trace hierarchy fetch
GENERATE_SUMMARY_TIMEOUT_SECONDS = 120  # 2 minutes per summary generation (includes LLM call)
EMIT_EVENTS_TIMEOUT_SECONDS = 60  # 1 minute for batch event emission

# Retry configuration
MAX_RETRY_ATTEMPTS_SAMPLE = 3  # Retries for sampling activity
MAX_RETRY_ATTEMPTS_FETCH = 3  # Retries for fetching trace hierarchy
MAX_RETRY_ATTEMPTS_SUMMARIZE = 2  # Retries for LLM summarization (fewer due to cost)
MAX_RETRY_ATTEMPTS_EMIT = 3  # Retries for event emission

# Event schema
EVENT_NAME_TRACE_SUMMARY = "$ai_trace_summary"  # Event name for summary storage

# Property keys for $ai_trace_summary events
PROP_TRACE_ID = "$ai_trace_id"
PROP_BATCH_RUN_ID = "$ai_batch_run_id"
PROP_SUMMARY_MODE = "$ai_summary_mode"
PROP_SUMMARY_TITLE = "$ai_summary_title"
PROP_SUMMARY_TEXT_REPR = "$ai_summary_text_repr"
PROP_SUMMARY_FLOW_DIAGRAM = "$ai_summary_flow_diagram"
PROP_SUMMARY_BULLETS = "$ai_summary_bullets"
PROP_SUMMARY_INTERESTING_NOTES = "$ai_summary_interesting_notes"
PROP_TEXT_REPR_LENGTH = "$ai_text_repr_length"
PROP_EVENT_COUNT = "$ai_event_count"

# Team allowlist - only these teams will be processed by the coordinator
# Empty list means all teams are allowed
ALLOWED_TEAM_IDS: list[int] = [
    1,  # Local development
    2,  # Internal PostHog project
    112495,  # Dogfooding project
]

# Temporal configuration
WORKFLOW_NAME = "batch-trace-summarization"
TASK_QUEUE = "llm-analytics-queue"
