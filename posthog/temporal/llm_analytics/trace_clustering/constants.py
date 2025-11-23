"""Configuration constants for trace clustering workflow."""

from datetime import timedelta

# Clustering parameters
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_MAX_SAMPLES = 100  # Reduced for dev - was 2000
DEFAULT_MIN_K = 2  # Reduced for dev - was 3
DEFAULT_MAX_K = 4  # Reduced for dev - was 6

# Minimum traces required for clustering
MIN_TRACES_FOR_CLUSTERING = 5  # Reduced for dev - was 20

# Workflow timeouts (reduced for dev)
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=5)  # Reduced for dev - was 30
QUERY_EMBEDDINGS_TIMEOUT = timedelta(minutes=2)  # Reduced for dev - was 5
SAMPLE_EMBEDDINGS_TIMEOUT = timedelta(seconds=30)  # Reduced for dev - was 1 min
DETERMINE_OPTIMAL_K_TIMEOUT = timedelta(minutes=2)  # Reduced for dev - was 10
PERFORM_CLUSTERING_TIMEOUT = timedelta(minutes=1)  # Reduced for dev - was 5
EMIT_EVENTS_TIMEOUT = timedelta(seconds=30)  # Reduced for dev - was 1 min

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

# Cluster labeling configuration
DEFAULT_TRACES_PER_CLUSTER_FOR_LABELING = 7  # Number of representative traces to use for LLM labeling
GENERATE_LABELS_TIMEOUT = timedelta(minutes=2)  # Timeout for LLM label generation activity
