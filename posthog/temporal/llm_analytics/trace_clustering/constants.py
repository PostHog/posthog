"""Configuration constants for trace clustering workflow."""

from datetime import timedelta

from temporalio.common import RetryPolicy

# Clustering parameters
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_MAX_SAMPLES = 5000
DEFAULT_MIN_K = 2
DEFAULT_MAX_K = 10

# Minimum traces required for clustering
MIN_TRACES_FOR_CLUSTERING = 20

# Workflow timeouts
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=30)
QUERY_EMBEDDINGS_TIMEOUT = timedelta(minutes=5)
SAMPLE_EMBEDDINGS_TIMEOUT = timedelta(minutes=1)
DETERMINE_OPTIMAL_K_TIMEOUT = timedelta(minutes=10)
PERFORM_CLUSTERING_TIMEOUT = timedelta(minutes=5)
EMIT_EVENTS_TIMEOUT = timedelta(minutes=1)
CLUSTERING_ACTIVITY_TIMEOUT = timedelta(minutes=30)

# Activity retry configuration
MAX_ACTIVITY_RETRIES = 2
ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=MAX_ACTIVITY_RETRIES + 1,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
)

# Coordinator retry policies
COORDINATOR_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=3)
COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=2)

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
GENERATE_LABELS_TIMEOUT = timedelta(minutes=5)  # Timeout for LLM label generation activity
