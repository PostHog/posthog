"""Configuration constants for video segment clustering workflow."""

from datetime import timedelta

from temporalio.common import RetryPolicy

# Scheduling
CLUSTERING_INTERVAL = timedelta(minutes=30)
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_LOOKBACK_WINDOW = timedelta(days=DEFAULT_LOOKBACK_DAYS)

# Minimum segments required for clustering
# Below this threshold, segments are accumulated for the next run
MIN_SEGMENTS_FOR_CLUSTERING = 3

# Clustering parameters (relaxed for small datasets)
MIN_CLUSTER_SIZE = 2  # Allow pairs of similar segments to form clusters
MIN_SAMPLES = 1  # Less conservative - allows more clusters to form
CLUSTER_SELECTION_METHOD = "leaf"  # Produces more granular clusters
CLUSTER_SELECTION_EPSILON = 0.0  # No epsilon for leaf method

# Task matching threshold (for deduplication)
TASK_MATCH_THRESHOLD = 0.3  # Cosine distance - lower = more strict matching

# PCA dimensionality reduction
TARGET_DIMENSIONALITY_FOR_CLUSTERING = 100  # Reduce from 3072 to 100 dimensions for clustering

# Embeddings configuration
EMBEDDING_MODEL = "text-embedding-3-large-3072"
EMBEDDING_DIMENSION = 3072
PRODUCT = "session-replay"
DOCUMENT_TYPE = "video-segment"
RENDERING = "video-analysis"

# Concurrency settings
MAX_CONCURRENT_TEAMS = 3

# Workflow timeouts
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=30)

# Activity timeouts
FETCH_ACTIVITY_TIMEOUT = timedelta(seconds=120)
CLUSTER_ACTIVITY_TIMEOUT = timedelta(seconds=180)
MATCH_ACTIVITY_TIMEOUT = timedelta(seconds=60)
LLM_ACTIVITY_TIMEOUT = timedelta(seconds=300)
TASK_ACTIVITY_TIMEOUT = timedelta(seconds=120)
LINK_ACTIVITY_TIMEOUT = timedelta(seconds=60)

# Session priming (summarization) settings
FETCH_SESSIONS_ACTIVITY_TIMEOUT = timedelta(seconds=60)
SUMMARIZE_SESSIONS_ACTIVITY_TIMEOUT = timedelta(minutes=30)

# Retry policies
COMPUTE_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
)

LLM_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)

DB_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
)

COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=2)

SESSION_PRIMING_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)

# Cluster labeling configuration
DEFAULT_SEGMENT_SAMPLES_PER_CLUSTER_FOR_LABELING = 5
LABELING_LLM_MODEL = "gemini-3-flash-preview"
