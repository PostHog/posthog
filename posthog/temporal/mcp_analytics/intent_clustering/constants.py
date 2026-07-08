"""Configuration constants for the MCP analytics intent clustering workflow.

Timeouts and retry policies mirror ``posthog/temporal/ai_observability/trace_clustering/constants.py``
— the workloads have the same shape (CPU-bound compute → external embedding
worker → ClickHouse-backed aggregates → ClickHouse write). Diverging numbers
without a real reason creates two competing reference points; reuse keeps
both pipelines comparable in Grafana.
"""

from datetime import timedelta

from temporalio.common import RetryPolicy

# Workflow identity --------------------------------------------------------

WORKFLOW_NAME = "mcpa-intent-clustering"
COORDINATOR_WORKFLOW_NAME = "mcpa-intent-clustering-coordinator"
COORDINATOR_SCHEDULE_ID = "mcpa-intent-clustering-coordinator-schedule"
CHILD_WORKFLOW_ID_PREFIX = "mcpa-intent-clustering-team"

# Sampling ------------------------------------------------------------------

DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_TOP_N_INTENTS = 500
MIN_INTENTS_FOR_CLUSTERING = 2

# Workflow + activity envelopes --------------------------------------------

WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=20)
COORDINATOR_EXECUTION_TIMEOUT = timedelta(hours=12)  # < daily schedule interval

# Per-activity, per single attempt.
COMPUTE_ACTIVITY_TIMEOUT = timedelta(seconds=180)  # corpus fetch + embed + cluster
JOURNEYS_ACTIVITY_TIMEOUT = timedelta(seconds=60)  # HogQL journey aggregation
SNAPSHOT_ACTIVITY_TIMEOUT = timedelta(seconds=30)  # pure-CPU snapshot assembly
PERSIST_ACTIVITY_TIMEOUT = timedelta(seconds=30)  # Postgres write

# Heartbeats let Temporal detect dead workers without waiting for the full
# start-to-close to elapse. Activities heartbeat at least this often.
COMPUTE_HEARTBEAT_TIMEOUT = timedelta(seconds=60)
JOURNEYS_HEARTBEAT_TIMEOUT = timedelta(seconds=30)
SNAPSHOT_HEARTBEAT_TIMEOUT = timedelta(seconds=30)
PERSIST_HEARTBEAT_TIMEOUT = timedelta(seconds=30)

# Schedule-to-close caps total time across retries + backoff + queue wait.
# Each is sized as (max_attempts × start_to_close) + a backoff allowance.
COMPUTE_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=400)
JOURNEYS_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=200)  # 3 × 60s + ~6s backoff allowance + buffer
SNAPSHOT_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=90)
PERSIST_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(seconds=90)

# Compute activity — CPU bound, quick retries. ValueError/TypeError are
# programming bugs that won't fix themselves on retry.
COMPUTE_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValueError", "TypeError"],
)

# Journeys activity — ClickHouse-backed, may hit query limits. Retry once
# with backoff to ride out transient cluster load.
JOURNEYS_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=20),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValueError", "TypeError"],
)

# Snapshot activity — pure CPU. A failure here means a code bug — retrying
# won't help.
SNAPSHOT_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=1,
    non_retryable_error_types=["ValueError", "TypeError", "AssertionError"],
)

# Persist activity — Postgres write. Retry on transient connection errors.
PERSIST_ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    non_retryable_error_types=["ValueError", "TypeError"],
)

# Coordinator — child-workflow failure shouldn't retry the whole coordinator.
COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=1)
COORDINATOR_DEFAULT_MAX_CONCURRENT_TEAMS = 4
