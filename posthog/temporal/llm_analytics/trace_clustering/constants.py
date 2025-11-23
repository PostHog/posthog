"""Configuration constants for trace clustering workflow."""

from datetime import timedelta

# Clustering parameters
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_MAX_SAMPLES = 2000
DEFAULT_MIN_K = 3
DEFAULT_MAX_K = 6

# Minimum traces required for clustering
MIN_TRACES_FOR_CLUSTERING = 20

# Workflow timeouts
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=30)
QUERY_EMBEDDINGS_TIMEOUT = timedelta(minutes=5)
SAMPLE_EMBEDDINGS_TIMEOUT = timedelta(minutes=1)
DETERMINE_OPTIMAL_K_TIMEOUT = timedelta(minutes=10)
PERFORM_CLUSTERING_TIMEOUT = timedelta(minutes=5)
EMIT_EVENTS_TIMEOUT = timedelta(minutes=1)

# Activity retry configuration
MAX_ACTIVITY_RETRIES = 2

# Event properties
CLUSTERING_VERSION = "v1"
EVENT_NAME = "$ai_trace_clusters"

# Rendering types for embeddings (from trace_summarization)
LLMA_TRACE_MINIMAL_RENDERING = "llma_trace_minimal"
LLMA_TRACE_DETAILED_RENDERING = "llma_trace_detailed"

# Team allowlist (empty list = all teams allowed)
ALLOWED_TEAM_IDS: list[int] = [
    1,  # Local development
    2,  # Internal PostHog project
    112495,  # Dogfooding project
]
