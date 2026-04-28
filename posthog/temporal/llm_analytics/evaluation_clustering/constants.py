"""Constants for evaluation-level clustering."""

from datetime import timedelta

from temporalio.common import RetryPolicy

# Stage A (sampler): window + offset + caps
SAMPLER_WINDOW_MINUTES = 60
SAMPLER_WINDOW_OFFSET_MINUTES = 30  # skew the window into the past so evals have time to land
SAMPLER_MAX_SAMPLES_PER_JOB = 250
SAMPLER_SCHEDULE_INTERVAL_HOURS = 1
SAMPLER_DEFAULT_MAX_CONCURRENT_TEAMS = 20

# Stage A timeouts
SAMPLER_ACTIVITY_TIMEOUT = timedelta(seconds=300)
SAMPLER_ACTIVITY_SCHEDULE_TO_CLOSE = timedelta(seconds=600)
SAMPLER_ACTIVITY_HEARTBEAT = timedelta(seconds=60)

SAMPLER_WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=15)
SAMPLER_COORDINATOR_EXECUTION_TIMEOUT = timedelta(minutes=55)  # finish before next hourly trigger

SAMPLER_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    non_retryable_error_types=["ValueError", "TypeError"],
)
SAMPLER_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=1)

# Stage B (clustering): mostly reuses trace_clustering constants (HDBSCAN/UMAP params, timeouts).
# Additional defaults specific to evaluation clustering:
CLUSTERING_MAX_SAMPLES = 1500  # read cap per clustering run
CLUSTERING_SCHEDULE_INTERVAL_HOURS = 24
# Daily schedule offset in hours — spreads load relative to the trace/generation coordinators,
# which run at their natural start-of-day cadence.
CLUSTERING_SCHEDULE_OFFSET_HOURS = 6

# Temporal identifiers
SAMPLER_WORKFLOW_NAME = "llma-evaluation-sampler"
SAMPLER_COORDINATOR_WORKFLOW_NAME = "llma-evaluation-sampler-coordinator"
SAMPLER_COORDINATOR_SCHEDULE_ID = "llma-evaluation-sampler-schedule"
SAMPLER_CHILD_WORKFLOW_ID_PREFIX = "llma-evaluation-sampler-team"

CLUSTERING_WORKFLOW_NAME = "llma-evaluation-clustering"
CLUSTERING_COORDINATOR_WORKFLOW_NAME = "llma-evaluation-clustering-coordinator"
CLUSTERING_COORDINATOR_SCHEDULE_ID = "llma-evaluation-clustering-coordinator-schedule"
CLUSTERING_CHILD_WORKFLOW_ID_PREFIX = "llma-evaluation-clustering-team"

# Embeddings
# Distinct document_type so eval embeddings live alongside trace/generation ones in
# raw_document_embeddings without overlap. Matches the "-detailed" suffix convention
# used by trace/generation summary embeddings.
LLMA_EVALUATION_DOCUMENT_TYPE = "llm-evaluation-detailed"
LLMA_EVALUATION_PRODUCT = "llm-analytics"

# Embedding model. Eval text representations are short (typically <1000 chars:
# evaluator name + one-line description + verdict + reasoning), so the 1536-dim
# small model is the default choice over the 3072-dim large model used by
# trace/generation summary embeddings — ~5x cheaper on OpenAI's embeddings API
# and half the storage in ClickHouse. Stage B filters raw_document_embeddings by
# this `model_name` so eval clustering only reads from the matching subtable in
# the union view.
LLMA_EVALUATION_EMBEDDING_MODEL = "text-embedding-3-small-1536"

# Event emitted by Stage B
EVENT_NAME_EVALUATION_CLUSTERS = "$ai_evaluation_clusters"

# Minimum accumulated embeddings required before clustering will run for a job.
# For a new eval job sampling up to 250/hour this is typically reached within an hour
# of activity; until then the Stage B workflow reports "not enough embeddings yet".
MIN_EMBEDDINGS_FOR_CLUSTERING = 20
